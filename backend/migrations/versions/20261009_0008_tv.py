"""TV subscription products and order details

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

from app.modules.services.seed import seed_tv_statements

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        "tv_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("operator_code", sa.String(20), nullable=False),
        sa.Column("operator_name", sa.String(60), nullable=False),
        sa.Column("provider_operator_id", sa.String(40), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("listed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tv_products")),
        sa.UniqueConstraint("provider_code", "provider_service_id", name="uq_tv_products_provider_service"),
    )
    op.create_index("ix_tv_products_listing", "tv_products", ["operator_code", "sort_order"],
                    postgresql_where=sa.text("listed AND active"))
    for sql, params in seed_tv_statements():
        op.execute(sa.text(sql).bindparams(**params))
    op.create_table(
        "tv_orders",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("operator_code", sa.String(20), nullable=False),
        sa.Column("operator_name", sa.String(60), nullable=False),
        sa.Column("product_name", sa.String(80), nullable=False),
        sa.Column("smartcard_number", sa.String(24), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("current_bouquet", sa.String(80), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_tv_orders")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_tv_orders_transaction_id_transactions")),
    )


def downgrade() -> None:
    raise RuntimeError("transaction history migrations are not reversible")
