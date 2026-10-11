import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.errors import ConflictError
from app.core.security import encode_token, hash_secret, keyed_digest, verify_secret
from app.modules.audit import service as audit
from app.modules.auth.errors import (
    InvalidCredentialsError, InvalidPinError, PinLockedError, PinNotSetError, WeakPinError,
)
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import Credential, User
from redis.asyncio import Redis

PIN_MAX_FAILURES = 5
PIN_LOCK = timedelta(minutes=30)
_SEQUENCES = "0123456789" + "9876543210"


def validate_pin_strength(pin: str) -> None:
    if len(set(pin)) == 1 or pin in _SEQUENCES:
        raise WeakPinError()


class PinService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.db, self.redis, self.settings = db, redis, settings
        self.repo = AuthRepository(db)

    def _pin_input(self, user_id: uuid.UUID, pin: str) -> str:
        # Peppered with a server-side key: a 4-digit PIN is brute-forceable from a leaked hash alone.
        return keyed_digest(self.settings.encryption_key.get_secret_value(), "pin", str(user_id), pin)

    async def _check(self, user: User, cred: Credential, pin: str, ip: str) -> None:
        now = datetime.now(UTC)
        if cred.pin_locked_until and cred.pin_locked_until > now:
            raise PinLockedError()
        if not cred.pin_hash:
            raise PinNotSetError()
        if not await verify_secret(cred.pin_hash, self._pin_input(user.id, pin)):
            cred.pin_failed_count += 1
            locked = cred.pin_failed_count >= PIN_MAX_FAILURES
            if locked:
                cred.pin_locked_until, cred.pin_failed_count = now + PIN_LOCK, 0
            audit.record(self.db, action="auth.pin_failed", actor_user_id=user.id, ip=ip,
                         meta={"locked": locked})
            await self.db.commit()
            raise InvalidPinError()
        cred.pin_failed_count = 0

    async def set_pin(self, user: User, password: str, pin: str, ip: str) -> None:
        await ratelimit.hit(self.redis, f"rl:pin:{user.id}", 20, 900)
        cred = await self.repo.credential(user.id, lock=True)
        assert cred is not None
        if cred.pin_hash:
            raise ConflictError("A PIN is already set. Use change PIN instead.")
        if not await verify_secret(cred.password_hash, password):
            audit.record(self.db, action="auth.pin_set_bad_password", actor_user_id=user.id, ip=ip)
            await self.db.commit()
            raise InvalidCredentialsError()
        validate_pin_strength(pin)
        cred.pin_hash = await hash_secret(self._pin_input(user.id, pin))
        cred.pin_changed_at = datetime.now(UTC)
        audit.record(self.db, action="auth.pin_set", actor_user_id=user.id, ip=ip)
        await self.db.commit()

    async def change_pin(self, user: User, current_pin: str, new_pin: str, ip: str) -> None:
        await ratelimit.hit(self.redis, f"rl:pin:{user.id}", 20, 900)
        cred = await self.repo.credential(user.id, lock=True)
        assert cred is not None
        await self._check(user, cred, current_pin, ip)
        validate_pin_strength(new_pin)
        cred.pin_hash = await hash_secret(self._pin_input(user.id, new_pin))
        cred.pin_changed_at = datetime.now(UTC)
        audit.record(self.db, action="auth.pin_changed", actor_user_id=user.id, ip=ip)
        await self.db.commit()

    async def verify_pin(self, user: User, pin: str, ip: str) -> str:
        """Returns a short-lived step-up token that money-moving endpoints will require."""
        await ratelimit.hit(self.redis, f"rl:pin:{user.id}", 20, 900)
        cred = await self.repo.credential(user.id, lock=True)
        assert cred is not None
        await self._check(user, cred, pin, ip)
        await self.db.commit()
        return encode_token(self.settings.jwt_secret.get_secret_value(), "pin", str(user.id),
                            timedelta(seconds=self.settings.step_up_ttl_s))
