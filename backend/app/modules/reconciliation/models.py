import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    run_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), default="RUNNING", server_default="RUNNING")
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','CLEAN','ISSUES','FAILED')", name="status"),
        Index("ix_reconciliation_runs_started", "started_at"),
    )


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(80))
    classification: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("classification IN ('MISMATCH','MISSING_INTERNAL','UNBALANCED','STUCK_PENDING')", name="classification"),
        Index("ix_reconciliation_records_run", "run_id", "id"),
        Index("ix_reconciliation_records_entity", "entity_type", "entity_id"),
    )
