from datetime import UTC, datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.core.money import Money
from app.modules.notifications.service import record_notification
from app.modules.promotions.models import PromoCampaign, PromoRedemption
from app.modules.transactions.models import Transaction
from app.modules.transactions.state import TxnStatus
from app.modules.wallet.service import WalletService
from app.modules.ledger.interface import SystemAccount


async def redeem_campaign(db: AsyncSession, user_id, raw_code: str) -> dict:
    code = raw_code.strip().upper()
    now = datetime.now(UTC)
    campaign = (await db.execute(select(PromoCampaign).where(PromoCampaign.code == code).with_for_update())).scalar_one_or_none()
    if campaign is None or not campaign.active or (campaign.starts_at and campaign.starts_at > now) or (campaign.ends_at and campaign.ends_at <= now):
        raise HTTPException(status_code=422, detail="This promo code is invalid or no longer active.")
    prior = await db.scalar(select(PromoRedemption.id).where(
        PromoRedemption.campaign_id == campaign.id, PromoRedemption.user_id == user_id))
    if prior:
        raise HTTPException(status_code=409, detail="You have already redeemed this promo code.")
    used = await db.scalar(select(func.count()).select_from(PromoRedemption).where(PromoRedemption.campaign_id == campaign.id))
    if campaign.max_redemptions is not None and int(used or 0) >= campaign.max_redemptions:
        raise HTTPException(status_code=409, detail="This promo code has reached its redemption limit.")
    if campaign.minimum_qualifying_purchase_kobo:
        qualifying = await db.scalar(select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id, Transaction.status == TxnStatus.SUCCESSFUL.value,
            Transaction.price_kobo >= campaign.minimum_qualifying_purchase_kobo))
        if not qualifying:
            raise HTTPException(status_code=422, detail="Complete an eligible successful bill payment before redeeming this code.")
    ref = f"promo:{campaign.code}:{user_id}"
    redemption = PromoRedemption(campaign_id=campaign.id, user_id=user_id,
                                 reward_kobo=campaign.reward_kobo, journal_reference=ref)
    db.add(redemption)
    await db.flush()
    amount = Money(campaign.reward_kobo)
    await WalletService(db).credit(user_id, amount, reference=ref, kind="promotion.reward",
        source=SystemAccount.DISCOUNTS, description=f"Promotion reward: {campaign.code}",
        meta={"campaign_id": str(campaign.id), "promo_code": campaign.code})
    await record_notification(db, user_id=user_id, event_key=f"promotion:redeemed:{campaign.id}:{user_id}",
        category="PROMOTION", title="Promo reward added",
        body=f"NGN {amount.naira_str()} from promo code {campaign.code} was added to your wallet.",
        resource_type="promotion", resource_reference=campaign.code,
        payload={"amount_kobo": amount.kobo, "code": campaign.code})
    await db.commit()
    return {"code": campaign.code, "reward_kobo": amount.kobo, "journal_reference": ref,
            "redeemed_at": redemption.created_at.isoformat() if redemption.created_at else now.isoformat()}
