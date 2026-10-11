from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.notifications.models import Notification, NotificationDelivery, NotificationPreference
from app.modules.users.models import User



async def record_notification(
    db: AsyncSession, *, user_id: uuid.UUID, event_key: str, category: str, title: str,
    body: str, resource_type: str | None = None, resource_reference: str | None = None,
    payload: dict | None = None,
) -> None:
    stmt = insert(Notification).values(
        id=uuid7(), user_id=user_id, event_key=event_key, category=category, title=title, body=body,
        resource_type=resource_type, resource_reference=resource_reference, payload=payload or {},
    ).on_conflict_do_nothing(index_elements=[Notification.event_key]).returning(Notification.id)
    notification_id = (await db.execute(stmt)).scalar_one_or_none()
    if notification_id is None:
        return
    pref = await db.get(NotificationPreference, user_id)
    user = await db.get(User, user_id)
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    if pref.email_enabled and pref.email_address:
        db.add(NotificationDelivery(notification_id=notification_id, channel="EMAIL", destination=pref.email_address))
    if pref.sms_enabled and user and user.phone:
        db.add(NotificationDelivery(notification_id=notification_id, channel="SMS", destination=user.phone))
    if pref.push_enabled:
        # Push destinations are device-specific and will be queued once a device token is registered.
        # No delivery is created without a valid destination.
        pass


def delivery_retry_time(attempts: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=min(30 * (2 ** min(attempts, 10)), 6 * 3600))
