from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_ctx
from app.modules.audit.models import AuditLog


def record(
    db: AsyncSession, *, action: str, actor_user_id: Any = None, resource_type: str | None = None,
    resource_id: str | None = None, ip: str | None = None, session_id: str | None = None,
    before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Stage an audit row in the caller's transaction. Never pass secrets in before/after/meta."""
    db.add(AuditLog(
        action=action, actor_user_id=actor_user_id, resource_type=resource_type,
        resource_id=resource_id, ip=ip, session_id=session_id, request_id=request_id_ctx.get(),
        before=before, after=after, meta=meta,
    ))
