"""pricing, provider prices, transactions, snapshots

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

from app.modules.ledger.accounts import SYSTEM_ACCOUNT_TYPES
from app.core.ids import uuid7
from app.modules.services.ddl import PRICING_DDL
from app.modules.services.seed import seed_statements

revision = "0004"
down_revision = "0003"
NOW = sa.text("now()")
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "provider_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(40), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(8), server_default="SEED", nullable=False),
        sa.Column("synced_at", TZ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_prices")),
        sa.UniqueConstraint("provider_code", "category", "scope_key", "provider_service_id", name="uq_provider_prices_key"),
        sa.CheckConstraint("kind IN ('DISCOUNT_BPS','FIXED_KOBO')", name=op.f("ck_provider_prices_kind")),
        sa.CheckConstraint("source IN ('SEED','SYNCED','MANUAL')", name=op.f("ck_provider_prices_source")),
        sa.CheckConstraint("value >= 0", name=op.f("ck_provider_prices_value_non_negative")),
    )
    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("provider_code", sa.String(20)),
        sa.Column("scope_key", sa.String(40)),
        sa.Column("tier", sa.String(20), server_default="DEFAULT", nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("markup_bps", sa.Integer()),
        sa.Column("markup_kobo", sa.BigInteger()),
        sa.Column("custom_price_kobo", sa.BigInteger()),
        sa.Column("fee_kobo", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("discount_bps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("discount_kobo", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("referral_bps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cap_at_face", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allow_subsidy", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("subsidy_reason", sa.String(200)),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("note", sa.String(200), server_default="", nullable=False),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.Column("deactivated_at", TZ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_rules")),
        sa.CheckConstraint("method IN ('PERCENT_MARKUP','FIXED_MARKUP','CUSTOM_PRICE')", name=op.f("ck_pricing_rules_method")),
        sa.CheckConstraint(
            "(method = 'PERCENT_MARKUP' AND markup_bps IS NOT NULL) OR "
            "(method = 'FIXED_MARKUP' AND markup_kobo IS NOT NULL) OR "
            "(method = 'CUSTOM_PRICE' AND custom_price_kobo IS NOT NULL AND custom_price_kobo > 0)",
            name=op.f("ck_pricing_rules_method_fields")),
        sa.CheckConstraint("fee_kobo >= 0 AND discount_kobo >= 0", name=op.f("ck_pricing_rules_non_negative")),
        sa.CheckConstraint("discount_bps BETWEEN 0 AND 10000 AND referral_bps BETWEEN 0 AND 10000", name=op.f("ck_pricing_rules_bps_range")),
    )
    op.create_index("uq_pricing_rules_active_scope", "pricing_rules",
                    ["category", sa.text("coalesce(provider_code, '')"), sa.text("coalesce(scope_key, '')"), "tier"],
                    unique=True, postgresql_where=sa.text("active"))
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("service_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("price_kobo", sa.BigInteger(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("provider_service_id", sa.String(40), nullable=False),
        sa.Column("provider_reference", sa.String(80)),
        sa.Column("provider_cost_kobo", sa.BigInteger()),
        sa.Column("hold_journal_reference", sa.String(120)),
        sa.Column("settle_journal_reference", sa.String(120)),
        sa.Column("refund_journal_reference", sa.String(120)),
        sa.Column("failure_reason", sa.String(200)),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("verify_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sent_at", TZ), sa.Column("next_check_at", TZ), sa.Column("escalated_at", TZ), sa.Column("completed_at", TZ),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.Column("updated_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_transactions_user_id_users")),
        sa.UniqueConstraint("reference", name=op.f("uq_transactions_reference")),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_transactions_user_idempotency"),
        sa.CheckConstraint("status IN ('INITIATED','PENDING','PROCESSING','SUCCESSFUL','FAILED','REVERSED','REFUNDED','UNKNOWN')", name=op.f("ck_transactions_status")),
        sa.CheckConstraint("amount_kobo > 0 AND price_kobo > 0", name=op.f("ck_transactions_amounts_positive")),
    )
    op.create_index("ix_transactions_user_id_id", "transactions", ["user_id", "id"])
    op.create_index("uq_transactions_provider_ref", "transactions", ["provider_code", "provider_reference"], unique=True,
                    postgresql_where=sa.text("provider_reference IS NOT NULL"))
    op.create_index("ix_transactions_open", "transactions", ["status", "updated_at"],
                    postgresql_where=sa.text("status IN ('PENDING','PROCESSING','UNKNOWN')"))
    op.create_index("ix_transactions_completed", "transactions", ["completed_at"],
                    postgresql_where=sa.text("completed_at IS NOT NULL"))
    op.create_table(
        "airtime_orders",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(10), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_airtime_orders")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_airtime_orders_transaction_id_transactions")),
    )
    op.create_table(
        "transaction_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(12)),
        sa.Column("to_status", sa.String(12), nullable=False),
        sa.Column("note", sa.String(200), server_default="", nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_events")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_transaction_events_transaction_id_transactions")),
    )
    op.create_index("ix_transaction_events_txn", "transaction_events", ["transaction_id", "id"])
    op.create_table(
        "provider_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("call", sa.String(12), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(80)),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(200), server_default="", nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_transactions")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_provider_transactions_transaction_id_transactions")),
    )
    op.create_index("ix_provider_transactions_txn", "provider_transactions", ["transaction_id", "created_at"])
    op.create_table(
        "pricing_snapshots",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid()),
        sa.Column("rule_version", sa.Integer()),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("provider_code", sa.String(20), nullable=False),
        sa.Column("cost_source", sa.String(8), nullable=False),
        *[sa.Column(c, sa.BigInteger(), nullable=False) for c in (
            "cost_kobo", "markup_kobo", "fee_kobo", "list_price_kobo", "discount_kobo", "customer_price_kobo",
            "referral_commission_kobo")],
        sa.Column("processing_cost_kobo", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        *[sa.Column(c, sa.BigInteger(), nullable=False) for c in (
            "gross_profit_before_discount_kobo", "gross_profit_kobo", "net_contribution_kobo")],
        sa.Column("margin_pct", sa.Numeric(7, 2), nullable=False),
        sa.Column("capped", sa.Boolean(), nullable=False),
        sa.Column("subsidized", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_pricing_snapshots")),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], name=op.f("fk_pricing_snapshots_transaction_id_transactions")),
        sa.ForeignKeyConstraint(["rule_id"], ["pricing_rules.id"], name=op.f("fk_pricing_snapshots_rule_id_pricing_rules")),
    )
    for stmt in PRICING_DDL:
        op.execute(stmt)
    for code, typ in SYSTEM_ACCOUNT_TYPES.items():
        op.execute(sa.text("INSERT INTO ledger_accounts (id, code, type, currency) VALUES (:id, :code, :type, 'NGN') "
                           "ON CONFLICT (code) DO NOTHING").bindparams(id=uuid7(), code=code.value, type=typ.value))
    for sql, params in seed_statements():
        op.execute(sa.text(sql).bindparams(**params))


def downgrade() -> None:
    raise RuntimeError("transaction and pricing history migrations are not reversible")
