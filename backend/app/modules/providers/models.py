import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class ProviderPrice(Base):
    """What the provider charges us. Synced from the provider; admin can override (source=MANUAL)."""

    __tablename__ = "provider_prices"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_code: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str] = mapped_column(String(40))          # network / DISCO / plan / exam
    provider_service_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(16))               # DISCOUNT_BPS | FIXED_KOBO
    value: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(8), default="SEED", server_default="SEED")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider_code", "category", "scope_key", "provider_service_id", name="uq_provider_prices_key"),
        CheckConstraint("kind IN ('DISCOUNT_BPS','FIXED_KOBO')", name="kind"),
        CheckConstraint("source IN ('SEED','SYNCED','MANUAL')", name="source"),
        CheckConstraint("value >= 0", name="value_non_negative"),
    )


class ProviderTransaction(Base):
    """Append-only log of every call we make to a provider (for reconciliation and disputes)."""

    __tablename__ = "provider_transactions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"))
    provider_code: Mapped[str] = mapped_column(String(20))
    call: Mapped[str] = mapped_column(String(12))               # PURCHASE | STATUS
    request_id: Mapped[str] = mapped_column(String(64))
    provider_reference: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(12))
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_provider_transactions_txn", "transaction_id", "created_at"),)


class DataPlan(Base):
    """Provider data plans. Discovered by sync as unlisted: an admin must review pricing and list them."""

    __tablename__ = "data_plans"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_code: Mapped[str] = mapped_column(String(20))
    provider_service_id: Mapped[str] = mapped_column(String(40))
    network: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(40))
    data_type: Mapped[str] = mapped_column(String(40), default="", server_default="")
    validity: Mapped[str] = mapped_column(String(40), default="", server_default="")
    listed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider_code", "provider_service_id", name="uq_data_plans_provider_service"),
        Index("ix_data_plans_listing", "network", "sort_order", postgresql_where=text("listed AND active")),
    )
