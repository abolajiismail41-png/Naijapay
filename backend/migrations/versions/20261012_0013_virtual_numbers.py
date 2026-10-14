"""Add SMS-Man virtual number orders.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "virtual_number_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("country_id", sa.Integer(), nullable=False),
        sa.Column("country_name", sa.String(length=100), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("provider_request_id", sa.BigInteger(), nullable=True),
        sa.Column("phone_number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("provider_cost_kobo", sa.BigInteger(), nullable=False),
        sa.Column("selling_price_kobo", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="NGN", nullable=False),
        sa.Column("sms_code", sa.Text(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.String(length=200), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','ACTIVE','SMS_RECEIVED','UNKNOWN','FAILED','CANCELLING','CANCELLED')", name="ck_virtual_number_orders_status_values"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
        sa.UniqueConstraint("provider_request_id"),
        sa.UniqueConstraint("user_id", "transaction_id", name="uq_vnumber_user_transaction"),
    )
    op.create_index("ix_virtual_number_orders_user_id", "virtual_number_orders", ["user_id"])
    op.create_index("ix_virtual_number_orders_status", "virtual_number_orders", ["status"])
    op.create_index("ix_vnumber_user_created", "virtual_number_orders", ["user_id", "created_at"])
    op.create_table(
        "virtual_number_pricing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("markup_percent", sa.Numeric(7, 3), nullable=False, server_default="15"),
        sa.Column("fixed_fee_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("min_price_kobo", sa.BigInteger(), nullable=False, server_default="100"),
        sa.Column("max_price_kobo", sa.BigInteger(), nullable=False, server_default="5000000"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_virtual_number_pricing_singleton"),
        sa.CheckConstraint("markup_percent >= 0 AND markup_percent <= 500", name="ck_virtual_number_pricing_markup_range"),
        sa.CheckConstraint("fixed_fee_kobo >= 0 AND min_price_kobo > 0 AND max_price_kobo >= min_price_kobo", name="ck_virtual_number_pricing_fee_price_range"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO virtual_number_pricing (id, markup_percent, fixed_fee_kobo, min_price_kobo, max_price_kobo, enabled) VALUES (1, 15, 0, 100, 5000000, true)")


def downgrade() -> None:
    op.drop_table("virtual_number_pricing")
    op.drop_index("ix_vnumber_user_created", table_name="virtual_number_orders")
    op.drop_index("ix_virtual_number_orders_status", table_name="virtual_number_orders")
    op.drop_index("ix_virtual_number_orders_user_id", table_name="virtual_number_orders")
    op.drop_table("virtual_number_orders")
