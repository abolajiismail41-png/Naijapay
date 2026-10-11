import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class FraudCaseStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class FraudCase(Base):
    __tablename__ = "fraud_cases"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    rule_code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(12))
    score: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default=FraudCaseStatus.OPEN.value, server_default="OPEN")
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    resolution_note: Mapped[str | None] = mapped_column(String(300))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("transaction_id", "rule_code", name="uq_fraud_cases_transaction_rule"),
        CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="severity"),
        CheckConstraint("status IN ('OPEN','REVIEWING','CLEARED','CONFIRMED')", name="status"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        Index("ix_fraud_cases_status_created", "status", "created_at"),
        Index("ix_fraud_cases_user_created", "user_id", "created_at"),
    )
