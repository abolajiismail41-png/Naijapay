import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class Wallet(Base):
    """`balance_kobo` is a cache of the ledger, updated in the same transaction as the journal."""

    __tablename__ = "wallets"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"), unique=True)
    balance_kobo: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("balance_kobo >= 0", name="balance_non_negative"),
        CheckConstraint("status IN ('ACTIVE','FROZEN')", name="status"),
    )
