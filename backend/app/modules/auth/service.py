import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import (
    digest, encode_token, hash_secret, keyed_digest, new_otp, new_refresh_token, verify_secret,
)
from app.modules.audit import service as audit
from app.modules.auth.errors import (
    AccountLockedError, InvalidCredentialsError, InvalidOtpError,
)
from app.modules.auth.models import OtpRequest, UserSession
from app.modules.auth.otp_sender import OtpSender
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import Credential, User, UserStatus

OTP_MAX_ATTEMPTS = 5
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK = timedelta(minutes=15)
OTP_IP_LIMIT, OTP_PHONE_LIMIT, OTP_WINDOW_S = 20, 3, 600
LOGIN_IP_LIMIT, LOGIN_PHONE_LIMIT, LOGIN_WINDOW_S = 30, 10, 900


class OtpPurpose(StrEnum):
    REGISTER = "register"
    PASSWORD_RESET = "password_reset"


@dataclass(frozen=True)
class ClientContext:
    ip: str
    user_agent: str | None = None
    device_label: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings, sender: OtpSender) -> None:
        self.db, self.redis, self.settings, self.sender = db, redis, settings, sender
        self.repo = AuthRepository(db)
        self._secret = settings.jwt_secret.get_secret_value()

    # ---------- OTP ----------
    async def _issue_otp(self, phone: str, purpose: OtpPurpose) -> None:
        now, code = _now(), new_otp()
        await self.repo.invalidate_otps(phone, purpose.value, now)
        self.db.add(OtpRequest(
            phone=phone, purpose=purpose.value,
            code_hash=keyed_digest(self._secret, phone, purpose.value, code),
            expires_at=now + timedelta(minutes=self.settings.otp_ttl_min)))
        await self.db.flush()
        await self.sender.send(phone, code, purpose.value)

    async def _consume_otp(self, phone: str, purpose: OtpPurpose, code: str) -> None:
        now = _now()
        row = await self.repo.active_otp(phone, purpose.value)
        if row is None or row.expires_at <= now or row.attempts >= OTP_MAX_ATTEMPTS:
            raise InvalidOtpError()
        expected = keyed_digest(self._secret, phone, purpose.value, code)
        if not hmac.compare_digest(expected, row.code_hash):
            row.attempts += 1
            await self.db.commit()
            raise InvalidOtpError()
        row.consumed_at = now

    async def _limit_otp(self, phone: str, ctx: ClientContext) -> None:
        await ratelimit.hit(self.redis, f"rl:otp:ip:{ctx.ip}", OTP_IP_LIMIT, 3600)
        await ratelimit.hit(self.redis, f"rl:otp:phone:{phone}", OTP_PHONE_LIMIT, OTP_WINDOW_S)

    # ---------- tokens / sessions ----------
    async def _new_session(self, user: User, family_id: uuid.UUID, ctx: ClientContext) -> TokenPair:
        now, refresh = _now(), new_refresh_token()
        self.db.add(UserSession(
            user_id=user.id, family_id=family_id, token_hash=digest(refresh),
            device_label=(ctx.device_label or None) and ctx.device_label[:80],
            ip=ctx.ip, user_agent=(ctx.user_agent or None) and ctx.user_agent[:255],
            expires_at=now + timedelta(days=self.settings.refresh_token_ttl_days)))
        ttl = timedelta(minutes=self.settings.access_token_ttl_min)
        access = encode_token(self._secret, "access", str(user.id), ttl, sid=str(family_id))
        await self.db.flush()
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=int(ttl.total_seconds()))

    async def _mark_revoked(self, family_ids: list[uuid.UUID]) -> None:
        """Make already-issued access tokens die immediately instead of at expiry."""
        ttl = self.settings.access_token_ttl_min * 60
        for fid in family_ids:
            await self.redis.set(f"revoked:fam:{fid}", 1, ex=ttl)

    # ---------- flows ----------
    async def register(self, phone: str, password: str, full_name: str, email: str, ctx: ClientContext, referral_code: str | None = None) -> TokenPair:
        """Create an account and start a session without requiring OTP.

        Phone syntax is validated by RegisterIn/Phone before this service is called.
        The number remains unverified until the optional phone-verification flow succeeds.
        """
        await ratelimit.hit(self.redis, f"rl:register:ip:{ctx.ip}", 10, 3600)
        await ratelimit.hit(self.redis, f"rl:register:phone:{phone}", 3, 3600)
        password_hash = await hash_secret(password)
        user = await self.repo.user_by_phone(phone, lock=True)
        if user is not None:
            # Never reset credentials or issue a session for an existing account via signup.
            audit.record(self.db, action="auth.register_existing_phone", actor_user_id=user.id, ip=ctx.ip)
            await self.db.commit()
            raise ConflictError("An account with this phone number may already exist. Try logging in.")

        user = User(phone=phone, full_name=full_name.strip(), email=email.strip().lower())
        self.db.add(user)
        await self.db.flush()
        self.db.add(Credential(user_id=user.id, password_hash=password_hash))
        if referral_code:
            from app.modules.referrals.service import ReferralCodeError, attach_referral
            try:
                await attach_referral(self.db, user.id, referral_code)
            except ReferralCodeError as exc:
                await self.db.rollback()
                from app.core.errors import AppError
                raise AppError(str(exc)) from None
        # Deliberately do not set phone_verified_at: registration is password-based,
        # and a phone-format check is not proof of ownership.
        tokens = await self._new_session(user, uuid.uuid4(), ctx)
        audit.record(self.db, action="auth.register", actor_user_id=user.id, ip=ctx.ip)
        await self.db.commit()
        return tokens

    async def request_phone_verification(self, user: User, ctx: ClientContext) -> None:
        """Optional post-registration phone verification; never blocks account login."""
        if user.phone_verified_at is not None:
            return
        await self._limit_otp(user.phone, ctx)
        await self._issue_otp(user.phone, OtpPurpose.REGISTER)
        audit.record(self.db, action="auth.phone_verification_requested", actor_user_id=user.id, ip=ctx.ip)
        await self.db.commit()

    async def verify_phone(self, phone: str, code: str, ctx: ClientContext) -> TokenPair:
        await ratelimit.hit(self.redis, f"rl:verify:ip:{ctx.ip}", 30, 900)
        await self._consume_otp(phone, OtpPurpose.REGISTER, code)
        user = await self.repo.user_by_phone(phone, lock=True)
        if user is None:
            raise InvalidOtpError()
        user.phone_verified_at = user.phone_verified_at or _now()
        tokens = await self._new_session(user, uuid.uuid4(), ctx)
        audit.record(self.db, action="auth.phone_verified", actor_user_id=user.id, ip=ctx.ip)
        await self.db.commit()
        return tokens

    async def login(self, phone: str, password: str, ctx: ClientContext) -> TokenPair:
        await ratelimit.hit(self.redis, f"rl:login:ip:{ctx.ip}", LOGIN_IP_LIMIT, LOGIN_WINDOW_S)
        await ratelimit.hit(self.redis, f"rl:login:phone:{phone}", LOGIN_PHONE_LIMIT, LOGIN_WINDOW_S)
        now = _now()
        user = await self.repo.user_by_phone(phone, lock=True)
        if user and user.locked_until and user.locked_until > now:
            audit.record(self.db, action="auth.login_blocked_locked", actor_user_id=user.id, ip=ctx.ip)
            await self.db.commit()
            raise AccountLockedError()
        cred = await self.repo.credential(user.id) if user else None
        if not await verify_secret(cred.password_hash if cred else None, password):
            if user:
                user.failed_login_count += 1
                locked = user.failed_login_count >= LOGIN_MAX_FAILURES
                if locked:
                    user.locked_until, user.failed_login_count = now + LOGIN_LOCK, 0
                audit.record(self.db, action="auth.login_failed", actor_user_id=user.id, ip=ctx.ip,
                             meta={"locked": locked})
                await self.db.commit()
            raise InvalidCredentialsError()
        assert user is not None
        if user.status != UserStatus.ACTIVE.value:
            raise ForbiddenError("This account is not available. Please contact support.")
        user.failed_login_count, user.locked_until = 0, None
        tokens = await self._new_session(user, uuid.uuid4(), ctx)
        audit.record(self.db, action="auth.login", actor_user_id=user.id, ip=ctx.ip)
        await self.db.commit()
        return tokens

    async def refresh(self, refresh_token: str, ctx: ClientContext) -> TokenPair:
        now = _now()
        row = await self.repo.session_by_hash(digest(refresh_token))  # FOR UPDATE serialises races
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            raise UnauthorizedError("Your session has expired. Please sign in again.")
        if row.rotated_at is not None:
            await self.repo.revoke_family(row.family_id, row.user_id, now)
            audit.record(self.db, action="auth.refresh_reuse_detected", actor_user_id=row.user_id,
                         ip=ctx.ip, session_id=str(row.family_id))
            await self.db.commit()
            await self._mark_revoked([row.family_id])
            raise UnauthorizedError("Your session has expired. Please sign in again.")
        user = await self.db.get(User, row.user_id)
        if user is None or user.status != UserStatus.ACTIVE.value:
            raise UnauthorizedError("Your session has expired. Please sign in again.")
        row.rotated_at = now
        tokens = await self._new_session(user, row.family_id, ctx)
        await self.db.commit()
        return tokens

    async def logout(self, user_id: uuid.UUID, family_id: uuid.UUID, ctx: ClientContext) -> None:
        await self.repo.revoke_family(family_id, user_id, _now())
        audit.record(self.db, action="auth.logout", actor_user_id=user_id, ip=ctx.ip,
                     session_id=str(family_id))
        await self.db.commit()
        await self._mark_revoked([family_id])

    async def list_sessions(self, user_id: uuid.UUID, current_family: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.repo.active_sessions(user_id, _now())
        return [{"id": str(r.family_id), "device": r.device_label, "ip": r.ip,
                 "created_at": r.created_at.isoformat(), "current": r.family_id == current_family}
                for r in rows]

    async def revoke_session(self, user_id: uuid.UUID, family_id: uuid.UUID, ctx: ClientContext) -> None:
        if not await self.repo.revoke_family(family_id, user_id, _now()):
            raise NotFoundError("Session not found.")
        audit.record(self.db, action="auth.session_revoked", actor_user_id=user_id, ip=ctx.ip,
                     session_id=str(family_id))
        await self.db.commit()
        await self._mark_revoked([family_id])

    async def request_password_reset(self, phone: str, ctx: ClientContext) -> None:
        await self._limit_otp(phone, ctx)
        user = await self.repo.user_by_phone(phone)
        if user and user.status == UserStatus.ACTIVE.value:
            # The OTP itself proves control of the number; registration no longer
            # requires verification, so do not gate password recovery on an old flag.
            await self._issue_otp(phone, OtpPurpose.PASSWORD_RESET)
            audit.record(self.db, action="auth.password_reset_requested", actor_user_id=user.id, ip=ctx.ip)
            await self.db.commit()

    async def confirm_password_reset(self, phone: str, code: str, new_password: str,
                                     ctx: ClientContext) -> None:
        await ratelimit.hit(self.redis, f"rl:verify:ip:{ctx.ip}", 30, 900)
        await self._consume_otp(phone, OtpPurpose.PASSWORD_RESET, code)
        user = await self.repo.user_by_phone(phone, lock=True)
        cred = await self.repo.credential(user.id, lock=True) if user else None
        if user is None or cred is None:
            raise InvalidOtpError()
        cred.password_hash = await hash_secret(new_password)
        cred.password_changed_at = _now()
        user.failed_login_count, user.locked_until = 0, None
        families = await self.repo.live_family_ids(user.id)
        await self.repo.revoke_all(user.id, _now())
        audit.record(self.db, action="auth.password_reset", actor_user_id=user.id, ip=ctx.ip)
        await self.db.commit()
        await self._mark_revoked(families)
