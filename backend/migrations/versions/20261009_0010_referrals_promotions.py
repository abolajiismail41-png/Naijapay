"""Referral attribution/rewards and promotion campaigns/redemptions.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.create_table(
        "referral_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("code", name=op.f("uq_referral_profiles_code")),
    )
    op.create_table(
        "referral_attributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("referrer_user_id", sa.Uuid(), nullable=False),
        sa.Column("referred_user_id", sa.Uuid(), nullable=False),
        sa.Column("referral_code", sa.String(16), nullable=False),
        sa.Column("status", sa.String(12), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name=op.f("uq_referral_attributions_referred_user_id")),
        sa.CheckConstraint("status IN ('PENDING','REWARDED','INELIGIBLE')", name=op.f("ck_referral_attributions_status")),
        sa.CheckConstraint("referrer_user_id <> referred_user_id", name=op.f("ck_referral_attributions_not_self_referral")),
    )
    op.create_index("ix_referral_attributions_referrer", "referral_attributions", ["referrer_user_id", "created_at"])
    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attribution_id", sa.Uuid(), nullable=False),
        sa.Column("referrer_user_id", sa.Uuid(), nullable=False),
        sa.Column("referred_user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("journal_reference", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attribution_id"], ["referral_attributions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referrer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referred_user_id", name=op.f("uq_referral_rewards_referred_user_id")),
        sa.UniqueConstraint("transaction_id", name=op.f("uq_referral_rewards_transaction_id")),
        sa.UniqueConstraint("journal_reference", name=op.f("uq_referral_rewards_journal_reference")),
        sa.CheckConstraint("amount_kobo > 0", name=op.f("ck_referral_rewards_amount_positive")),
    )
    op.create_table(
        "promo_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), server_default="", nullable=False),
        sa.Column("reward_kobo", sa.BigInteger(), nullable=False),
        sa.Column("minimum_qualifying_purchase_kobo", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name=op.f("uq_promo_campaigns_code")),
        sa.CheckConstraint("reward_kobo > 0", name=op.f("ck_promo_campaigns_reward_positive")),
        sa.CheckConstraint("minimum_qualifying_purchase_kobo >= 0", name=op.f("ck_promo_campaigns_minimum_nonnegative")),
        sa.CheckConstraint("max_redemptions IS NULL OR max_redemptions > 0", name=op.f("ck_promo_campaigns_max_redemptions_positive")),
        sa.CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name=op.f("ck_promo_campaigns_date_range")),
    )
    op.create_index("ix_promo_campaigns_active", "promo_campaigns", ["active", "starts_at", "ends_at"])
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reward_kobo", sa.BigInteger(), nullable=False),
        sa.Column("journal_reference", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["promo_campaigns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_promo_redemption_campaign_user"),
        sa.UniqueConstraint("journal_reference", name=op.f("uq_promo_redemptions_journal_reference")),
        sa.CheckConstraint("reward_kobo > 0", name=op.f("ck_promo_redemptions_reward_positive")),
    )
    op.create_index("ix_promo_redemptions_campaign", "promo_redemptions", ["campaign_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Referral and promotion financial history migrations are not reversible")
