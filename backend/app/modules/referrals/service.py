from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import uuid7
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import Direction, EntryLine, SystemAccount
from app.modules.notifications.service import record_notification
from app.modules.referrals.models import ReferralAttribution, ReferralProfile, ReferralReward
from app.modules.transactions.models import Transaction
from app.modules.transactions.state import TxnStatus
from app.modules.wallet.service import WalletService


class ReferralCodeError(ValueError):
    pass


def _new_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "NJP" + "".join(secrets.choice(alphabet) for _ in range(7))


async def ensure_profile(db: AsyncSession, user_id: uuid.UUID) -> ReferralProfile:
    profile = await db.get(ReferralProfile, user_id)
    if profile:
        return profile
    for _ in range(5):
        code = _new_code()
        result = await db.execute(insert(ReferralProfile).values(user_id=user_id, code=code)
                                  .on_conflict_do_nothing())
        if result.rowcount:
            await db.flush()
            return await db.get(ReferralProfile, user_id)  # type: ignore[return-value]
        profile = await db.get(ReferralProfile, user_id)
        if profile:
            return profile
    raise RuntimeError("Could not allocate a unique referral code")


async def attach_referral(db: AsyncSession, referred_user_id: uuid.UUID, code: str | None) -> None:
    if not code:
        return
    profile = (await db.execute(select(ReferralProfile).where(ReferralProfile.code == code.strip().upper())))\
        .scalar_one_or_none()
    if profile is None:
        raise ReferralCodeError("That referral code was not found.")
    if profile.user_id == referred_user_id:
        raise ReferralCodeError("You cannot use your own referral code.")
    existing = await db.get(ReferralAttribution, referred_user_id, populate_existing=True)
    if existing is not None:
        return
    db.add(ReferralAttribution(referrer_user_id=profile.user_id, referred_user_id=referred_user_id,
                               referral_code=profile.code, status="PENDING"))
    await db.flush()


async def reward_referrer_for_transaction(db: AsyncSession, txn: Transaction, settings: Settings) -> None:
    """Pays at most once, only on the referred user's first qualifying successful purchase."""
    reward_kobo = settings.referral_reward_kobo
    if reward_kobo <= 0 or txn.price_kobo < settings.referral_min_purchase_kobo:
        return
    attr = (await db.execute(select(ReferralAttribution).where(
        ReferralAttribution.referred_user_id == txn.user_id).with_for_update())).scalar_one_or_none()
    if attr is None or attr.status != "PENDING":
        return
    previous = await db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.user_id == txn.user_id, Transaction.status == TxnStatus.SUCCESSFUL.value,
        Transaction.price_kobo >= settings.referral_min_purchase_kobo, Transaction.id != txn.id))
    if previous:
        return
    existing = await db.scalar(select(ReferralReward.id).where(ReferralReward.referred_user_id == txn.user_id))
    if existing:
        attr.status = "REWARDED"
        return
    amount = Money(reward_kobo)
    # Accrue then immediately settle the payable to the referrer's wallet, in the same DB transaction.
    await ledger.post_journal(db, reference=f"referral:accrue:{txn.reference}", kind="referral.reward_accrual",
        lines=[EntryLine(await ledger.system_account_id(db, SystemAccount.REFERRAL_EXPENSE), Direction.DEBIT, amount),
               EntryLine(await ledger.system_account_id(db, SystemAccount.REFERRAL_PAYABLE), Direction.CREDIT, amount)],
        description="Referral reward accrued", meta={"transaction": txn.reference, "referrer": str(attr.referrer_user_id)})
    await WalletService(db).credit(attr.referrer_user_id, amount,
        reference=f"referral:pay:{txn.reference}", kind="referral.reward", source=SystemAccount.REFERRAL_PAYABLE,
        description="Referral reward", meta={"transaction": txn.reference, "referred_user_id": str(txn.user_id)})
    db.add(ReferralReward(attribution_id=attr.id, referrer_user_id=attr.referrer_user_id,
        referred_user_id=txn.user_id, transaction_id=txn.id, amount_kobo=reward_kobo,
        journal_reference=f"referral:pay:{txn.reference}"))
    attr.status, attr.rewarded_at = "REWARDED", datetime.now(UTC)
    await record_notification(db, user_id=attr.referrer_user_id, event_key=f"referral:reward:{txn.reference}",
        category="REFERRAL", title="Referral reward received",
        body=f"You received NGN {amount.naira_str()} for inviting a new NaijaPay customer.",
        resource_type="referral_reward", resource_reference=txn.reference,
        payload={"amount_kobo": reward_kobo, "transaction_reference": txn.reference})
    audit.record(db, action="referral.reward_paid", actor_user_id=attr.referrer_user_id,
                 resource_type="transaction", resource_id=txn.reference,
                 meta={"amount_kobo": reward_kobo, "referred_user_id": str(txn.user_id)})
