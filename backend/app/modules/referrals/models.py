from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


class ReferralProfile(Base):
    __tablename__ = "referral_profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferralAttribution(Base):
    __tablename__ = "referral_attributions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    referred_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    referral_code: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="PENDING", server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('PENDING','REWARDED','INELIGIBLE')", name="status"),
        CheckConstraint("referrer_user_id <> referred_user_id", name="not_self_referral"),
        Index("ix_referral_attributions_referrer", "referrer_user_id", "created_at"),
    )


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    attribution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referral_attributions.id", ondelete="RESTRICT"))
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    referred_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True)
    amount_kobo: Mapped[int] = mapped_column(BigInteger)
    journal_reference: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("amount_kobo > 0", name="amount_positive"),)
