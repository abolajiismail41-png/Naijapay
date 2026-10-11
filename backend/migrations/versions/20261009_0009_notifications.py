"""Durable notification inbox and external delivery queue.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_reference", sa.String(80), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_notifications_event_key"),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at", "id"])
    op.create_index("ix_notifications_unread", "notifications", ["user_id", "created_at"], postgresql_where=sa.text("read_at IS NULL"))
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sms_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("email_address", sa.String(254), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("destination", sa.String(254), nullable=False),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("provider_reference", sa.String(120), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "channel", name="uq_notification_delivery_channel"),
        sa.CheckConstraint("channel IN ('EMAIL','SMS','PUSH')", name="channel"),
        sa.CheckConstraint("status IN ('PENDING','SENDING','SENT','BLOCKED','DEAD')", name="status"),
    )
    op.create_index("ix_notification_delivery_due", "notification_deliveries", ["status", "next_attempt_at"])


def downgrade() -> None:
    raise RuntimeError("notification history migrations are not reversible")
