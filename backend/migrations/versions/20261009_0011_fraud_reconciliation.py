"""Fraud review cases and internal reconciliation runs.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.create_table(
        "fraud_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), server_default="OPEN", nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolution_note", sa.String(300), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "rule_code", name="uq_fraud_cases_transaction_rule"),
        sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name=op.f("ck_fraud_cases_severity")),
        sa.CheckConstraint("status IN ('OPEN','REVIEWING','CLEARED','CONFIRMED')", name=op.f("ck_fraud_cases_status")),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_fraud_cases_score_range")),
    )
    op.create_index("ix_fraud_cases_status_created", "fraud_cases", ["status", "created_at"])
    op.create_index("ix_fraud_cases_user_created", "fraud_cases", ["user_id", "created_at"])

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(12), server_default="RUNNING", nullable=False),
        sa.Column("started_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["started_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('RUNNING','CLEAN','ISSUES','FAILED')", name=op.f("ck_reconciliation_runs_status")),
    )
    op.create_index("ix_reconciliation_runs_started", "reconciliation_runs", ["started_at"])

    op.create_table(
        "reconciliation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("classification IN ('MISMATCH','MISSING_INTERNAL','UNBALANCED','STUCK_PENDING')", name=op.f("ck_reconciliation_records_classification")),
    )
    op.create_index("ix_reconciliation_records_run", "reconciliation_records", ["run_id", "id"])
    op.create_index("ix_reconciliation_records_entity", "reconciliation_records", ["entity_type", "entity_id"])


def downgrade() -> None:
    raise RuntimeError("Fraud and reconciliation evidence is operational/financial history and is not reversible")
