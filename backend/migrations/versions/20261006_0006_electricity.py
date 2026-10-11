"""electricity: discos, orders, FACE_VALUE pricing method

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

from app.modules.services.seed import seed_electricity_statements

revision = "0006"
down_revision = "0005"
NOW = sa.text("now()")
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_pricing_rules_method"), "pricing_rules", type_="check")
    op.create_check_constraint(op.f("ck_pricing_rules_method"), "pricing_rules",
                               "method IN ('PERCENT_MARKUP','FIXED_MARKUP','CUSTOM_PRICE','FACE_VALUE')")
    op.drop_constraint(op.f("ck_pricing_rules_method_fields"), "pricing_rules", type_="check")
    op.create_check_constraint(
        op.f("ck_pricing_rules_method_fields"), "pricing_rules",
        "(method = 'PERCENT_MARKUP' AND markup_bps IS NOT NULL) OR (method = 'FIXED_MARKUP' AND markup_kobo IS NOT NULL) OR "
        "(method = 'CUSTOM_PRICE' AND custom_price_kobo IS NOT NULL AND custom_price_kobo > 0) OR (method = 'FACE_VALUE')")
    op.create_table(
        "electricity_discos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("provider_disco_code", sa.String(40), nullable=False),
        sa.Column("prepaid_service_id", sa.String(40)),
        sa.Column("postpaid_service_id", sa.String(40)),
        sa.Column("listed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.Column("updated_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_electricity_discos")),
        sa.UniqueConstraint("provider_code", "code", name="uq_electricity_discos_provider_code"),
    )
    op.create_index("ix_electricity_discos_listing", "electricity_discos", ["sort_order"],
                    postgresql_where=sa.text("listed AND active"))
    op.create_table(
        "electricity_orders",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("disco_id", sa.Uuid(), nullable=False),
        sa.Column("disco_code", sa.String(20), nullable=False),
        sa.Column("disco_name", sa.String(80), nullable=False),
        sa.Column("provider_disco_code", sa.String(40), nullable=False),
        sa.Column("meter_type", sa.String(8), nullable=False),
        sa.Column("meter_number", sa.String(20), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_address", sa.String(200), server_default="", nullable=False),
        sa.Column("token_status", sa.String(14), server_default="PENDING", nullable=False),
        sa.Column("token_ciphertext", sa.String(400)),
        sa.Column("units", sa.String(20)),
        sa.Column("token_delivered_at", TZ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_electricity_orders")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_electricity_orders_transaction_id_transactions")),
    )
    for sql, params in seed_electricity_statements():
        op.execute(sa.text(sql).bindparams(**params))


def downgrade() -> None:
    raise RuntimeError("transaction history migrations are not reversible")
