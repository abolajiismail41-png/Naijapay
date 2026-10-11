"""ledger and wallet

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.ids import uuid7
from app.modules.ledger.accounts import SYSTEM_ACCOUNT_TYPES
from app.modules.ledger.ddl import LEDGER_DDL

revision = "0002"
down_revision = "0001"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), server_default="NGN", nullable=False),
        sa.Column("owner_user_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_accounts")),
        sa.UniqueConstraint("code", name=op.f("uq_ledger_accounts_code")),
        sa.CheckConstraint("type IN ('ASSET','LIABILITY','REVENUE','EXPENSE')", name=op.f("ck_ledger_accounts_type")),
    )
    op.create_table(
        "ledger_journals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("description", sa.String(200), server_default="", nullable=False),
        sa.Column("reverses_journal_id", sa.Uuid()),
        sa.Column("meta", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_journals")),
        sa.UniqueConstraint("reference", name=op.f("uq_ledger_journals_reference")),
        sa.UniqueConstraint("reverses_journal_id", name=op.f("uq_ledger_journals_reverses_journal_id")),
        sa.ForeignKeyConstraint(["reverses_journal_id"], ["ledger_journals.id"],
                                name=op.f("fk_ledger_journals_reverses_journal_id_ledger_journals")),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journal_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(1), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_entries")),
        sa.ForeignKeyConstraint(["journal_id"], ["ledger_journals.id"], name=op.f("fk_ledger_entries_journal_id_ledger_journals")),
        sa.ForeignKeyConstraint(["account_id"], ["ledger_accounts.id"], name=op.f("fk_ledger_entries_account_id_ledger_accounts")),
        sa.CheckConstraint("direction IN ('D','C')", name=op.f("ck_ledger_entries_direction")),
        sa.CheckConstraint("amount_kobo > 0", name=op.f("ck_ledger_entries_amount_positive")),
    )
    op.create_index("ix_ledger_entries_account_id", "ledger_entries", ["account_id", "id"])
    op.create_index("ix_ledger_entries_journal_id", "ledger_entries", ["journal_id"])
    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ledger_account_id", sa.Uuid(), nullable=False),
        sa.Column("balance_kobo", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallets")),
        sa.UniqueConstraint("user_id", name=op.f("uq_wallets_user_id")),
        sa.UniqueConstraint("ledger_account_id", name=op.f("uq_wallets_ledger_account_id")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_wallets_user_id_users")),
        sa.ForeignKeyConstraint(["ledger_account_id"], ["ledger_accounts.id"], name=op.f("fk_wallets_ledger_account_id_ledger_accounts")),
        sa.CheckConstraint("balance_kobo >= 0", name=op.f("ck_wallets_balance_non_negative")),
        sa.CheckConstraint("status IN ('ACTIVE','FROZEN')", name=op.f("ck_wallets_status")),
    )
    for stmt in LEDGER_DDL:
        op.execute(stmt)
    for code, typ in SYSTEM_ACCOUNT_TYPES.items():
        op.execute(sa.text(
            "INSERT INTO ledger_accounts (id, code, type, currency) VALUES (:id, :code, :type, 'NGN') "
            "ON CONFLICT (code) DO NOTHING"
        ).bindparams(id=uuid7(), code=code.value, type=typ.value))


def downgrade() -> None:
    # Destroying ledger history is deliberately blocked: restore from backup instead.
    raise RuntimeError("ledger migrations are not reversible")
