"""auth foundation: users, credentials, sessions, otp, audit

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.audit.ddl import IMMUTABLE_DDL

revision = "0001"
down_revision = None
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(16), server_default="USER", nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True)),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("phone", name=op.f("uq_users_phone")),
        sa.CheckConstraint("role IN ('USER','SUPPORT','FINANCE','ADMIN','SUPER_ADMIN')", name=op.f("ck_users_role")),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','CLOSED')", name=op.f("ck_users_status")),
    )
    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("pin_hash", sa.String(255)),
        sa.Column("pin_failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("pin_locked_until", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("pin_changed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_credentials_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_credentials")),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("device_label", sa.String(80)),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index("ix_user_sessions_family", "user_sessions", ["family_id"])
    op.create_index("ix_user_sessions_user_active", "user_sessions", ["user_id"],
                    postgresql_where=sa.text("revoked_at IS NULL AND rotated_at IS NULL"))
    op.create_table(
        "otp_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_requests")),
    )
    op.create_index("ix_otp_requests_lookup", "otp_requests", ["phone", "purpose", "created_at"])
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(48)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("ip", sa.String(45)),
        sa.Column("session_id", sa.String(64)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("meta", postgresql.JSONB()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id", "created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    for stmt in IMMUTABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
    for table in ("audit_logs", "otp_requests", "user_sessions", "user_credentials", "users"):
        op.drop_table(table)
