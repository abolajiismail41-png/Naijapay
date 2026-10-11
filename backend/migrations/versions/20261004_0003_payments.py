"""payments and webhook events

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("processor", sa.String(20), nullable=False),
        sa.Column("processor_reference", sa.String(80)),
        sa.Column("purpose", sa.String(24), server_default="WALLET_FUNDING", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("fee_kobo", sa.BigInteger(), nullable=False),
        sa.Column("charged_kobo", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("authorization_url", sa.String(500)),
        sa.Column("access_code", sa.String(80)),
        sa.Column("processor_txn_id", sa.String(40)),
        sa.Column("journal_reference", sa.String(120)),
        sa.Column("failure_reason", sa.String(200)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users")),
        sa.UniqueConstraint("reference", name=op.f("uq_payments_reference")),
        sa.UniqueConstraint("processor_reference", name=op.f("uq_payments_processor_reference")),
        sa.UniqueConstraint("processor_txn_id", name=op.f("uq_payments_processor_txn_id")),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_idempotency"),
        sa.CheckConstraint("status IN ('INITIATED','PENDING','SUCCESSFUL','FAILED','ABANDONED','MISMATCH')", name=op.f("ck_payments_status")),
        sa.CheckConstraint("amount_kobo > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint("fee_kobo >= 0", name=op.f("ck_payments_fee_non_negative")),
        sa.CheckConstraint("charged_kobo = amount_kobo + fee_kobo", name=op.f("ck_payments_charged_matches")),
    )
    op.create_index("ix_payments_user_id_id", "payments", ["user_id", "id"])
    op.create_index("ix_payments_open", "payments", ["status", "created_at"],
                    postgresql_where=sa.text("status IN ('INITIATED','PENDING')"))
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(80)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(12), server_default="RECEIVED", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
        sa.UniqueConstraint("source", "event_key", name="uq_webhook_events_source_event_key"),
        sa.CheckConstraint("status IN ('RECEIVED','PROCESSED','IGNORED','FAILED')", name=op.f("ck_webhook_events_status")),
    )
    op.create_index("ix_webhook_events_pending", "webhook_events", ["status", "received_at"],
                    postgresql_where=sa.text("status IN ('RECEIVED','FAILED')"))


def downgrade() -> None:
    raise RuntimeError("payment history migrations are not reversible")
