import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import OtpRequest, UserSession
from app.modules.users.models import Credential, User


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def user_by_phone(self, phone: str, *, lock: bool = False) -> User | None:
        q = select(User).where(User.phone == phone)
        return (await self.db.execute(q.with_for_update() if lock else q)).scalar_one_or_none()

    async def credential(self, user_id: uuid.UUID, *, lock: bool = False) -> Credential | None:
        q = select(Credential).where(Credential.user_id == user_id)
        return (await self.db.execute(q.with_for_update() if lock else q)).scalar_one_or_none()

    async def session_by_hash(self, token_hash: str) -> UserSession | None:
        q = select(UserSession).where(UserSession.token_hash == token_hash).with_for_update()
        return (await self.db.execute(q)).scalar_one_or_none()

    async def active_otp(self, phone: str, purpose: str) -> OtpRequest | None:
        q = (select(OtpRequest)
             .where(OtpRequest.phone == phone, OtpRequest.purpose == purpose,
                    OtpRequest.consumed_at.is_(None))
             .order_by(OtpRequest.created_at.desc()).limit(1).with_for_update())
        return (await self.db.execute(q)).scalar_one_or_none()

    async def invalidate_otps(self, phone: str, purpose: str, now: datetime) -> None:
        await self.db.execute(
            update(OtpRequest)
            .where(OtpRequest.phone == phone, OtpRequest.purpose == purpose,
                   OtpRequest.consumed_at.is_(None))
            .values(consumed_at=now))

    async def revoke_family(self, family_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> int:
        res = await self.db.execute(
            update(UserSession)
            .where(UserSession.family_id == family_id, UserSession.user_id == user_id,
                   UserSession.revoked_at.is_(None))
            .values(revoked_at=now))
        return res.rowcount or 0  # type: ignore[attr-defined,no-any-return]

    async def live_family_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        q = select(UserSession.family_id).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).distinct()
        return list((await self.db.execute(q)).scalars())

    async def revoke_all(self, user_id: uuid.UUID, now: datetime) -> None:
        await self.db.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now))

    async def active_sessions(self, user_id: uuid.UUID, now: datetime) -> list[UserSession]:
        q = (select(UserSession)
             .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None),
                    UserSession.rotated_at.is_(None), UserSession.expires_at > now)
             .order_by(UserSession.created_at.desc()))
        return list((await self.db.execute(q)).scalars())
