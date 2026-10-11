from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class Notification(Base):
    """Durable in-app inbox event. External delivery is tracked separately."""

    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_key: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_reference: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at", "id"),
        Index("ix_notifications_unread", "user_id", "created_at", postgresql_where=text("read_at IS NULL")),
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    email_address: Mapped[str | None] = mapped_column(String(254))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(12))
    destination: Mapped[str] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider_reference: Mapped[str | None] = mapped_column(String(120))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_notification_delivery_channel"),
        CheckConstraint("channel IN ('EMAIL','SMS','PUSH')", name="channel"),
        CheckConstraint("status IN ('PENDING','SENDING','SENT','BLOCKED','DEAD')", name="status"),
        Index("ix_notification_delivery_due", "status", "next_attempt_at"),
    )
