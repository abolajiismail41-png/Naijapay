from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ReferralSummary(BaseModel):
    code: str
    share_text: str
    total_invites: int
    pending_invites: int
    rewarded_invites: int
    total_rewards_kobo: int
    reward_enabled: bool
    reward_amount_kobo: int
    minimum_qualifying_purchase_kobo: int
    rewards: list["ReferralRewardRead"]


class ReferralRewardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    referred_user_id: UUID
    transaction_id: UUID
    amount_kobo: int
    created_at: datetime


class PromoRedeemIn(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
