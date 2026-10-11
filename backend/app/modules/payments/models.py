import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class PaymentStatus(StrEnum):
    INITIATED = "INITIATED"    # row created, processor not yet confirmed the checkout session
    PENDING = "PENDING"        # customer has a checkout URL, outcome unknown
    SUCCESSFUL = "SUCCESSFUL"  # processor-verified AND ledger credited
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    MISMATCH = "MISMATCH"      # processor says paid but amount/currency/reference disagree: finance review


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    processor: Mapped[str] = mapped_column(String(20))
    processor_reference: Mapped[str | None] = mapped_column(String(80), unique=True)
    purpose: Mapped[str] = mapped_column(String(24), default="WALLET_FUNDING", server_default="WALLET_FUNDING")
    status: Mapped[str] = mapped_column(String(16))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)   # what the wallet receives
    fee_kobo: Mapped[int] = mapped_column(BigInteger)
    charged_kobo: Mapped[int] = mapped_column(BigInteger)  # what the customer pays = amount + fee
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    authorization_url: Mapped[str | None] = mapped_column(String(500))
    access_code: Mapped[str | None] = mapped_column(String(80))
    processor_txn_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    journal_reference: Mapped[str | None] = mapped_column(String(120))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_idempotency"),
        CheckConstraint("status IN ('INITIATED','PENDING','SUCCESSFUL','FAILED','ABANDONED','MISMATCH')", name="status"),
        CheckConstraint("amount_kobo > 0", name="amount_positive"),
        CheckConstraint("fee_kobo >= 0", name="fee_non_negative"),
        CheckConstraint("charged_kobo = amount_kobo + fee_kobo", name="charged_matches"),
        Index("ix_payments_user_id_id", "user_id", "id"),
        Index("ix_payments_open", "status", "created_at",
              postgresql_where=text("status IN ('INITIATED','PENDING')")),
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    source: Mapped[str] = mapped_column(String(20))
    event_key: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="RECEIVED", server_default="RECEIVED")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source", "event_key", name="uq_webhook_events_source_event_key"),
        CheckConstraint("status IN ('RECEIVED','PROCESSED','IGNORED','FAILED')", name="status"),
        Index("ix_webhook_events_pending", "status", "received_at",
              postgresql_where=text("status IN ('RECEIVED','FAILED')")),
    )
