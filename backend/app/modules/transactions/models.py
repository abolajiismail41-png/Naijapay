import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class Transaction(Base):
    """Business record of one purchase. Money lives in the ledger; cost/markup live in pricing_snapshots."""

    __tablename__ = "transactions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    reference: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    service_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    amount_kobo: Mapped[int] = mapped_column(BigInteger)        # product value (airtime face value)
    price_kobo: Mapped[int] = mapped_column(BigInteger)         # what the customer was charged
    provider_code: Mapped[str] = mapped_column(String(20))
    provider_service_id: Mapped[str] = mapped_column(String(40))
    provider_reference: Mapped[str | None] = mapped_column(String(80))
    provider_cost_kobo: Mapped[int | None] = mapped_column(BigInteger)   # ACTUAL cost, known at success
    hold_journal_reference: Mapped[str | None] = mapped_column(String(120))
    settle_journal_reference: Mapped[str | None] = mapped_column(String(120))
    refund_journal_reference: Mapped[str | None] = mapped_column(String(120))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    verify_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_transactions_user_idempotency"),
        CheckConstraint("status IN ('INITIATED','PENDING','PROCESSING','SUCCESSFUL','FAILED','REVERSED','REFUNDED','UNKNOWN')", name="status"),
        CheckConstraint("amount_kobo > 0 AND price_kobo > 0", name="amounts_positive"),
        Index("ix_transactions_user_id_id", "user_id", "id"),
        Index("uq_transactions_provider_ref", "provider_code", "provider_reference", unique=True,
              postgresql_where=text("provider_reference IS NOT NULL")),
        Index("ix_transactions_open", "status", "updated_at",
              postgresql_where=text("status IN ('PENDING','PROCESSING','UNKNOWN')")),
        Index("ix_transactions_completed", "completed_at", postgresql_where=text("completed_at IS NOT NULL")),
    )


class AirtimeOrder(Base):
    __tablename__ = "airtime_orders"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    network: Mapped[str] = mapped_column(String(10))
    phone: Mapped[str] = mapped_column(String(16))


class DataOrder(Base):
    __tablename__ = "data_orders"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    network: Mapped[str] = mapped_column(String(10))
    phone: Mapped[str] = mapped_column(String(16))
    provider_service_id: Mapped[str] = mapped_column(String(40))
    plan_name: Mapped[str] = mapped_column(String(40))
    data_type: Mapped[str] = mapped_column(String(40), default="", server_default="")
    validity: Mapped[str] = mapped_column(String(40), default="", server_default="")


class ElectricityOrder(Base):
    __tablename__ = "electricity_orders"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    disco_id: Mapped[uuid.UUID] = mapped_column()
    disco_code: Mapped[str] = mapped_column(String(20))
    disco_name: Mapped[str] = mapped_column(String(80))
    provider_disco_code: Mapped[str] = mapped_column(String(40))
    meter_type: Mapped[str] = mapped_column(String(8))
    meter_number: Mapped[str] = mapped_column(String(20))
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_address: Mapped[str] = mapped_column(String(200), default="", server_default="")
    token_status: Mapped[str] = mapped_column(String(14), default="PENDING", server_default="PENDING")  # PENDING|DELIVERED|MISSING|NOT_APPLICABLE
    token_ciphertext: Mapped[str | None] = mapped_column(String(400))   # AES-GCM, bound to the transaction reference
    units: Mapped[str | None] = mapped_column(String(20))
    token_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EducationOrder(Base):
    __tablename__ = "education_orders"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column()
    product_code: Mapped[str] = mapped_column(String(20))
    product_name: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer)
    pins_status: Mapped[str] = mapped_column(String(10), default="PENDING", server_default="PENDING")  # PENDING|DELIVERED|PARTIAL|MISSING
    pins_ciphertext: Mapped[str | None] = mapped_column(Text)   # AES-GCM over a JSON list of {pin, serial}
    pins_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    pins_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransactionEvent(Base):
    __tablename__ = "transaction_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"))
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_transaction_events_txn", "transaction_id", "id"),)


class TVOrder(Base):
    __tablename__ = "tv_orders"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column()
    operator_code: Mapped[str] = mapped_column(String(20))
    operator_name: Mapped[str] = mapped_column(String(60))
    product_name: Mapped[str] = mapped_column(String(80))
    smartcard_number: Mapped[str] = mapped_column(String(24))
    customer_name: Mapped[str] = mapped_column(String(120))
    current_bouquet: Mapped[str] = mapped_column(String(80), default="", server_default="")
