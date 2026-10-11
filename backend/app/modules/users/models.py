import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.ids import uuid7


class Role(StrEnum):
    USER = "USER"
    SUPPORT = "SUPPORT"
    FINANCE = "FINANCE"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default=Role.USER.value, server_default="USER")
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.ACTIVE.value, server_default="ACTIVE")
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('USER','SUPPORT','FINANCE','ADMIN','SUPER_ADMIN')", name="role"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED','CLOSED')", name="status"),
    )


class Credential(Base):
    __tablename__ = "user_credentials"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    pin_failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pin_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
