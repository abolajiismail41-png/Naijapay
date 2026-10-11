import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class PricingRule(Base):
    """Admin-managed pricing. Never edited in place: a change deactivates the old row and adds a new version."""

    __tablename__ = "pricing_rules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    category: Mapped[str] = mapped_column(String(16))
    provider_code: Mapped[str | None] = mapped_column(String(20))
    scope_key: Mapped[str | None] = mapped_column(String(40))   # network / DISCO / TV plan / exam type
    tier: Mapped[str] = mapped_column(String(20), default="DEFAULT", server_default="DEFAULT")
    method: Mapped[str] = mapped_column(String(16))
    markup_bps: Mapped[int | None] = mapped_column(Integer)
    markup_kobo: Mapped[int | None] = mapped_column(BigInteger)
    custom_price_kobo: Mapped[int | None] = mapped_column(BigInteger)
    fee_kobo: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    discount_bps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    discount_kobo: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    referral_bps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rounding_kobo: Mapped[int] = mapped_column(BigInteger, default=1, server_default=text("1"))
    cap_at_face: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    allow_subsidy: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    subsidy_reason: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("method IN ('PERCENT_MARKUP','FIXED_MARKUP','CUSTOM_PRICE','FACE_VALUE')", name="method"),
        CheckConstraint(
            "(method = 'PERCENT_MARKUP' AND markup_bps IS NOT NULL) OR "
            "(method = 'FIXED_MARKUP' AND markup_kobo IS NOT NULL) OR "
            "(method = 'CUSTOM_PRICE' AND custom_price_kobo IS NOT NULL AND custom_price_kobo > 0) OR "
            "(method = 'FACE_VALUE')",
            name="method_fields"),
        CheckConstraint("fee_kobo >= 0 AND discount_kobo >= 0", name="non_negative"),
        CheckConstraint("discount_bps BETWEEN 0 AND 10000 AND referral_bps BETWEEN 0 AND 10000", name="bps_range"),
        CheckConstraint("rounding_kobo >= 1", name="rounding_positive"),
        Index("uq_pricing_rules_active_scope", "category", text("coalesce(provider_code, '')"),
              text("coalesce(scope_key, '')"), "tier", unique=True, postgresql_where=text("active")),
    )


class PricingSnapshot(Base):
    """Immutable record of the exact pricing used for one transaction."""

    __tablename__ = "pricing_snapshots"
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_rules.id"))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(16))
    provider_code: Mapped[str] = mapped_column(String(20))
    cost_source: Mapped[str] = mapped_column(String(8))
    cost_kobo: Mapped[int] = mapped_column(BigInteger)                 # expected provider cost at quote time
    markup_kobo: Mapped[int] = mapped_column(BigInteger)
    fee_kobo: Mapped[int] = mapped_column(BigInteger)
    list_price_kobo: Mapped[int] = mapped_column(BigInteger)
    discount_kobo: Mapped[int] = mapped_column(BigInteger)
    customer_price_kobo: Mapped[int] = mapped_column(BigInteger)
    referral_commission_kobo: Mapped[int] = mapped_column(BigInteger)
    processing_cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    gross_profit_before_discount_kobo: Mapped[int] = mapped_column(BigInteger)
    gross_profit_kobo: Mapped[int] = mapped_column(BigInteger)
    net_contribution_kobo: Mapped[int] = mapped_column(BigInteger)
    margin_pct: Mapped[float] = mapped_column(Numeric(7, 2))
    capped: Mapped[bool] = mapped_column(Boolean)
    subsidized: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
