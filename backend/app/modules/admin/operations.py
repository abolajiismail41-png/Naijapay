from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import client_ip, get_app_settings, get_db, get_redis, ok
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.models import UserSession
from app.modules.auth.rbac import Permission
from app.modules.transactions.models import Transaction
from app.modules.users.models import Role, User, UserStatus
from app.modules.wallet.models import Wallet

router = APIRouter(prefix="/api/v1/admin", tags=["admin-operations"])
LAGOS = ZoneInfo("Africa/Lagos")


class UserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ACTIVE", "SUSPENDED"]
    reason: str = Field(min_length=5, max_length=200)


def _user_view(user: User, wallet: Wallet | None = None) -> dict[str, Any]:
    return {
        "id": str(user.id), "full_name": user.full_name, "phone": user.phone,
        "role": user.role, "status": user.status,
        "phone_verified": user.phone_verified_at is not None,
        "created_at": user.created_at.isoformat(),
        "wallet": ({"balance_kobo": wallet.balance_kobo, "status": wallet.status}
                   if wallet else None),
    }


@router.get("/overview")
async def overview(
    _: Principal = Depends(require_permission(Permission.TRANSACTIONS_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Operational counts only; profit and monetary totals stay in the finance dashboard."""
    now = datetime.now(LAGOS)
    start = datetime.combine(now.date(), time.min, LAGOS)
    tomorrow = start + timedelta(days=1)
    user_counts = dict((await db.execute(
        select(User.status, func.count()).group_by(User.status)
    )).all())
    txn_counts = dict((await db.execute(
        select(Transaction.status, func.count()).group_by(Transaction.status)
    )).all())
    today_count = await db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.created_at >= start, Transaction.created_at < tomorrow))
    total_users = sum(int(n) for n in user_counts.values())
    total_transactions = sum(int(n) for n in txn_counts.values())
    return ok({
        "as_of": now.isoformat(), "timezone": "Africa/Lagos",
        "users": {"total": total_users, "active": int(user_counts.get("ACTIVE", 0)),
                  "suspended": int(user_counts.get("SUSPENDED", 0)),
                  "closed": int(user_counts.get("CLOSED", 0))},
        "transactions": {"total": total_transactions, "created_today": int(today_count or 0),
                         "pending": int(txn_counts.get("PENDING", 0)),
                         "processing": int(txn_counts.get("PROCESSING", 0)),
                         "unknown": int(txn_counts.get("UNKNOWN", 0)),
                         "failed": int(txn_counts.get("FAILED", 0)),
                         "successful": int(txn_counts.get("SUCCESSFUL", 0))},
    })


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, min_length=1, max_length=120),
    status: Literal["ACTIVE", "SUSPENDED", "CLOSED"] | None = None,
    cursor: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=25, ge=1, le=100),
    _: Principal = Depends(require_permission(Permission.USERS_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(User).order_by(User.id.desc()).limit(limit + 1)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        term = q.strip()
        filters = [User.phone.ilike(f"%{term}%"), User.full_name.ilike(f"%{term}%")]
        try:
            filters.append(User.id == uuid.UUID(term))
        except ValueError:
            pass
        stmt = stmt.where(or_(*filters))
    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="Invalid cursor.") from None
        stmt = stmt.where(User.id < cursor_id)
    rows = list((await db.execute(stmt)).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]
    wallets = {}
    if rows:
        wallets = {w.user_id: w for w in (await db.execute(
            select(Wallet).where(Wallet.user_id.in_([u.id for u in rows]))
        )).scalars()}
    return ok({"items": [_user_view(u, wallets.get(u.id)) for u in rows],
               "next_cursor": str(rows[-1].id) if has_more and rows else None})


@router.get("/users/{user_id}")
async def user_detail(
    user_id: uuid.UUID,
    _: Principal = Depends(require_permission(Permission.USERS_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user_id))).scalar_one_or_none()
    sessions = (await db.execute(select(func.count()).select_from(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None),
        UserSession.rotated_at.is_(None), UserSession.expires_at > datetime.now(LAGOS)
    ))).scalar_one()
    transactions = (await db.execute(select(Transaction.status, func.count()).where(
        Transaction.user_id == user_id).group_by(Transaction.status))).all()
    return ok(_user_view(user, wallet) | {
        "active_sessions": int(sessions),
        "transaction_counts": {status: int(count) for status, count in transactions},
    })


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found.")
    if user.id == principal.user.id:
        raise ConflictError("You cannot change your own account status.")
    if user.role != Role.USER.value and principal.user.role != Role.SUPER_ADMIN.value:
        raise ForbiddenError("Only a super administrator can change a staff account's status.")
    if user.status == UserStatus.CLOSED.value:
        raise ConflictError("Closed accounts cannot be reactivated through this endpoint.")
    if user.status == body.status:
        return ok(_user_view(user), "Account status unchanged.")

    before = {"status": user.status}
    user.status = body.status
    revoked_families: list[uuid.UUID] = []
    if body.status == UserStatus.SUSPENDED.value:
        now = datetime.now(LAGOS)
        revoked_families = list((await db.execute(select(UserSession.family_id).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        ).distinct())).scalars())
        # Fail closed: existing access tokens are invalidated immediately; DB refresh sessions
        # are also revoked so a later Redis restart does not revive them.
        for family_id in revoked_families:
            await redis.set(f"revoked:fam:{family_id}", 1, ex=settings.access_token_ttl_min * 60)
        await db.execute(update(UserSession).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        ).values(revoked_at=now))
    audit.record(db, action="admin.user_status_changed", actor_user_id=principal.user.id,
                 resource_type="user", resource_id=str(user.id), ip=client_ip(request),
                 session_id=str(principal.family_id), before=before,
                 after={"status": user.status}, meta={"reason": body.reason.strip(),
                                                       "revoked_session_families": len(revoked_families)})
    await db.commit()
    await db.refresh(user)
    wallet = (await db.execute(select(Wallet).where(Wallet.user_id == user.id))).scalar_one_or_none()
    return ok(_user_view(user, wallet), "Account status updated.")


@router.get("/audit")
async def audit_events(
    action: str | None = Query(default=None, min_length=1, max_length=64),
    resource_type: str | None = Query(default=None, min_length=1, max_length=48),
    cursor: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
    _: Principal = Depends(require_permission(Permission.AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="Invalid cursor.") from None
        stmt = stmt.where(AuditLog.id < cursor_id)
    rows = list((await db.execute(stmt)).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [{"id": str(r.id), "created_at": r.created_at.isoformat(),
              "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
              "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id,
              "ip": r.ip, "request_id": r.request_id, "before": r.before,
              "after": r.after, "meta": r.meta} for r in rows]
    return ok({"items": items, "next_cursor": str(rows[-1].id) if has_more and rows else None})
