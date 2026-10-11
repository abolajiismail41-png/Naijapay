"""data plans, data orders, price rounding

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

from app.modules.services.seed import seed_data_statements

revision = "0005"
down_revision = "0004"
NOW = sa.text("now()")
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("pricing_rules", sa.Column("rounding_kobo", sa.BigInteger(), server_default=sa.text("1"), nullable=False))
    op.create_check_constraint(op.f("ck_pricing_rules_rounding_positive"), "pricing_rules", "rounding_kobo >= 1")
    op.create_table(
        "data_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("network", sa.String(10), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("data_type", sa.String(40), server_default="", nullable=False),
        sa.Column("validity", sa.String(40), server_default="", nullable=False),
        sa.Column("listed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.Column("updated_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_plans")),
        sa.UniqueConstraint("provider_code", "provider_service_id", name="uq_data_plans_provider_service"),
    )
    op.create_index("ix_data_plans_listing", "data_plans", ["network", "sort_order"],
                    postgresql_where=sa.text("listed AND active"))
    op.create_table(
        "data_orders",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(10), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("plan_name", sa.String(40), nullable=False),
        sa.Column("data_type", sa.String(40), server_default="", nullable=False),
        sa.Column("validity", sa.String(40), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_data_orders")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_data_orders_transaction_id_transactions")),
    )
    for sql, params in seed_data_statements():
        op.execute(sa.text(sql).bindparams(**params))


def downgrade() -> None:
    raise RuntimeError("transaction history migrations are not reversible")
