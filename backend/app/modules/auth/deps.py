import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import client_ip, get_app_settings, get_db, get_redis
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.modules.audit import service as audit
from app.modules.auth.rbac import Permission, has_permission
from app.modules.users.models import User, UserStatus

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    family_id: uuid.UUID


async def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> Principal:
    if creds is None:
        raise UnauthorizedError()
    claims = decode_token(settings.jwt_secret.get_secret_value(), creds.credentials, "access")
    try:
        user_id, family_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (KeyError, ValueError):
        raise UnauthorizedError() from None
    if await redis.exists(f"revoked:fam:{family_id}"):
        raise UnauthorizedError("Your session has ended. Please sign in again.")
    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise UnauthorizedError()
    return Principal(user=user, family_id=family_id)  # role is read fresh from the DB every request


def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    async def dependency(request: Request, principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_db)) -> Principal:
        if not has_permission(principal.user.role, permission):
            audit.record(db, action="authz.denied", actor_user_id=principal.user.id,
                         ip=client_ip(request), meta={"permission": permission.value})
            await db.commit()
            raise ForbiddenError()
        return principal
    return dependency


@dataclass(frozen=True)
class PinStepUp:
    principal: Principal
    jti: str
    expires_at: int


async def require_pin_step_up(
    principal: Principal = Depends(current_principal), settings: Settings = Depends(get_app_settings),
    x_pin_token: str | None = Header(default=None),
) -> PinStepUp:
    if not x_pin_token:
        raise ForbiddenError("Please confirm with your transaction PIN.")
    claims = decode_token(settings.jwt_secret.get_secret_value(), x_pin_token, "pin")
    if claims["sub"] != str(principal.user.id) or "jti" not in claims:
        raise ForbiddenError("Please confirm with your transaction PIN.")
    return PinStepUp(principal, str(claims["jti"]), int(claims["exp"]))
