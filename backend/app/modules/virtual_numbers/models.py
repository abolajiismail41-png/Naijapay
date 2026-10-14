import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class VirtualNumberOrder(Base):
    __tablename__ = "virtual_number_orders"

    # `updated_at` is refreshed by the database (onupdate=func.now()).
    # Without eager_defaults, SQLAlchemy expires it after every UPDATE and the
    # next attribute read triggers a lazy load, which raises MissingGreenlet in
    # async sessions. eager_defaults fetches server-generated values via
    # RETURNING as part of the UPDATE/INSERT itself.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    country_id: Mapped[int] = mapped_column(Integer)
    country_name: Mapped[str] = mapped_column(String(100))
    application_id: Mapped[int] = mapped_column(Integer)
    service_name: Mapped[str] = mapped_column(String(100))
    provider_request_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    phone_number: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    provider_cost_kobo: Mapped[int] = mapped_column(BigInteger)
    selling_price_kobo: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    sms_code: Mapped[str | None] = mapped_column(Text)
    provider_error_code: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACTIVE','SMS_RECEIVED','UNKNOWN','FAILED','CANCELLING','CANCELLED')",
            name="status_values",
        ),
        UniqueConstraint("user_id", "transaction_id", name="uq_vnumber_user_transaction"),
        Index("ix_vnumber_user_created", "user_id", "created_at"),
    )


class VirtualNumberPricing(Base):
    __tablename__ = "virtual_number_pricing"

    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    markup_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=Decimal("15"))
    fixed_fee_kobo: Mapped[int] = mapped_column(BigInteger, default=0)
    min_price_kobo: Mapped[int] = mapped_column(BigInteger, default=100)
    max_price_kobo: Mapped[int] = mapped_column(BigInteger, default=5_000_000)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("markup_percent >= 0 AND markup_percent <= 500", name="markup_range"),
        CheckConstraint(
            "fixed_fee_kobo >= 0 AND min_price_kobo > 0 AND max_price_kobo >= min_price_kobo",
            name="fee_price_range",
        ),
    )