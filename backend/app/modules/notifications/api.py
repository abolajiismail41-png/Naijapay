from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.modules.auth.deps import Principal, current_principal
from app.modules.notifications.models import Notification, NotificationPreference
from app.modules.notifications.schemas import MarkRead, NotificationPage, PreferencesRead, PreferencesUpdate

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = Query(20, ge=1, le=50), cursor: str | None = None,
    principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Notification).where(Notification.user_id == principal.user.id)
    if cursor:
        try:
            cursor_id = UUID(cursor)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid notification cursor.") from None
        anchor = await db.get(Notification, cursor_id)
        if anchor is None or anchor.user_id != principal.user.id:
            raise HTTPException(status_code=422, detail="Invalid notification cursor.")
        stmt = stmt.where((Notification.created_at < anchor.created_at) |
                          ((Notification.created_at == anchor.created_at) & (Notification.id < anchor.id)))
    rows = list((await db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1))).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]
    unread = await db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == principal.user.id, Notification.read_at.is_(None)))
    page = NotificationPage(items=rows, next_cursor=str(rows[-1].id) if has_more and rows else None,
                            unread_count=int(unread or 0))
    return ok(page, "Notifications loaded.")


@router.post("/read")
async def mark_read(body: MarkRead, principal: Principal = Depends(current_principal),
                    db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(update(Notification).where(
        Notification.user_id == principal.user.id, Notification.id.in_(body.ids), Notification.read_at.is_(None)
    ).values(read_at=datetime.now(UTC)))
    await db.commit()
    return ok({"updated": result.rowcount or 0}, "Notifications marked as read.")


@router.post("/read-all")
async def mark_all_read(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(update(Notification).where(
        Notification.user_id == principal.user.id, Notification.read_at.is_(None)
    ).values(read_at=datetime.now(UTC)))
    await db.commit()
    return ok({"updated": result.rowcount or 0}, "Notifications marked as read.")


@router.get("/preferences")
async def get_preferences(principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_db)) -> dict:
    pref = await db.get(NotificationPreference, principal.user.id)
    if pref is None:
        pref = NotificationPreference(user_id=principal.user.id)
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return ok(PreferencesRead.model_validate(pref), "Notification preferences loaded.")


@router.patch("/preferences")
async def update_preferences(body: PreferencesUpdate, principal: Principal = Depends(current_principal),
                             db: AsyncSession = Depends(get_db)) -> dict:
    pref = await db.get(NotificationPreference, principal.user.id)
    if pref is None:
        pref = NotificationPreference(user_id=principal.user.id)
        db.add(pref)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("push_enabled") is True:
        raise HTTPException(status_code=422, detail="Push notifications are not available yet.")
    resulting_email_enabled = changes.get("email_enabled", pref.email_enabled)
    resulting_email = changes.get("email_address", pref.email_address)
    if resulting_email_enabled and not resulting_email:
        raise HTTPException(status_code=422, detail="Add an email address before enabling email notifications.")
    for key, value in changes.items():
        setattr(pref, key, value)
    await db.commit()
    await db.refresh(pref)
    return ok(PreferencesRead.model_validate(pref), "Notification preferences updated.")
