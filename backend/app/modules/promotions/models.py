from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class PromoCampaign(Base):
    __tablename__ = "promo_campaigns"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    reward_kobo: Mapped[int] = mapped_column(BigInteger)
    minimum_qualifying_purchase_kobo: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("reward_kobo > 0", name="reward_positive"),
        CheckConstraint("minimum_qualifying_purchase_kobo >= 0", name="minimum_nonnegative"),
        CheckConstraint("max_redemptions IS NULL OR max_redemptions > 0", name="max_redemptions_positive"),
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="date_range"),
        Index("ix_promo_campaigns_active", "active", "starts_at", "ends_at"),
    )


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("promo_campaigns.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reward_kobo: Mapped[int] = mapped_column(BigInteger)
    journal_reference: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("campaign_id", "user_id", name="uq_promo_redemption_campaign_user"),
        CheckConstraint("reward_kobo > 0", name="reward_positive"),
        Index("ix_promo_redemptions_campaign", "campaign_id", "created_at"),
    )
