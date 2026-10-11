import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    type: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3), default="NGN", server_default="NGN")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("type IN ('ASSET','LIABILITY','REVENUE','EXPENSE')", name="type"),
    )


class LedgerJournal(Base):
    """One balanced business event. `reference` is the idempotency key for the posting."""

    __tablename__ = "ledger_journals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    reference: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    request_hash: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(200), default="", server_default="")
    reverses_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_journals.id"), unique=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    journal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_journals.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"))
    direction: Mapped[str] = mapped_column(String(1))
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("direction IN ('D','C')", name="direction"),
        CheckConstraint("amount_kobo > 0", name="amount_positive"),
        Index("ix_ledger_entries_account_id", "account_id", "id"),
        Index("ix_ledger_entries_journal_id", "journal_id"),
    )
