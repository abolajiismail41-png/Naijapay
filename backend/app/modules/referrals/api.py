from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, ok
from app.modules.auth.deps import Principal, current_principal
from app.modules.referrals.models import ReferralAttribution, ReferralProfile, ReferralReward
from app.modules.referrals.schemas import ReferralRewardRead, ReferralSummary
from app.modules.referrals.service import ensure_profile

router = APIRouter(prefix="/api/v1/referrals", tags=["referrals"])


@router.get("/me")
async def my_referrals(principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_app_settings)) -> dict:
    profile = await ensure_profile(db, principal.user.id)
    total = await db.scalar(select(func.count()).select_from(ReferralAttribution).where(
        ReferralAttribution.referrer_user_id == principal.user.id))
    pending = await db.scalar(select(func.count()).select_from(ReferralAttribution).where(
        ReferralAttribution.referrer_user_id == principal.user.id, ReferralAttribution.status == "PENDING"))
    rewarded = await db.scalar(select(func.count()).select_from(ReferralReward).where(
        ReferralReward.referrer_user_id == principal.user.id))
    total_kobo = await db.scalar(select(func.coalesce(func.sum(ReferralReward.amount_kobo), 0)).where(
        ReferralReward.referrer_user_id == principal.user.id))
    rewards = list((await db.execute(select(ReferralReward).where(
        ReferralReward.referrer_user_id == principal.user.id).order_by(ReferralReward.created_at.desc()).limit(20))).scalars())
    await db.commit()
    result = ReferralSummary(code=profile.code,
        share_text=f"Join me on NaijaPay. Sign up with my referral code {profile.code} and start paying bills easily.",
        total_invites=int(total or 0), pending_invites=int(pending or 0), rewarded_invites=int(rewarded or 0),
        total_rewards_kobo=int(total_kobo or 0), reward_enabled=settings.referral_reward_kobo > 0,
        reward_amount_kobo=settings.referral_reward_kobo,
        minimum_qualifying_purchase_kobo=settings.referral_min_purchase_kobo,
        rewards=[ReferralRewardRead.model_validate(r) for r in rewards])
    return ok(result, "Referral summary loaded.")
