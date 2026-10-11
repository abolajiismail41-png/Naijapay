"""education: exam pin products and orders

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

from app.modules.services.seed import seed_education_statements

revision = "0007"
down_revision = "0006"
NOW = sa.text("now()")
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "education_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("max_quantity", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("listed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.Column("updated_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_education_products")),
        sa.UniqueConstraint("provider_code", "provider_service_id", name="uq_education_products_provider_service"),
    )
    op.create_index("ix_education_products_listing", "education_products", ["sort_order"],
                    postgresql_where=sa.text("listed AND active"))
    op.create_table(
        "education_orders",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(20), nullable=False),
        sa.Column("product_name", sa.String(80), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("pins_status", sa.String(10), server_default="PENDING", nullable=False),
        sa.Column("pins_ciphertext", sa.Text()),
        sa.Column("pins_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("pins_delivered_at", TZ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_education_orders")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_education_orders_transaction_id_transactions")),
    )
    for sql, params in seed_education_statements():
        op.execute(sa.text(sql).bindparams(**params))


def downgrade() -> None:
    raise RuntimeError("transaction history migrations are not reversible")
