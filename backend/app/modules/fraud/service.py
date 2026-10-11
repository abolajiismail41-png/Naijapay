from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.fraud.models import FraudCase
from app.modules.transactions.models import Transaction
from app.modules.users.models import User


def evaluate_signals(price_kobo: int, phone_verified: bool, velocity_count: int, settings: Settings):
    """Return deterministic, review-only rule signals for one transaction."""
    rules = []
    if price_kobo >= settings.fraud_high_value_kobo:
        rules.append(("HIGH_VALUE", "MEDIUM", 55, [{"signal": "price_threshold", "price_kobo": price_kobo}]))
    if not phone_verified and price_kobo >= settings.fraud_unverified_value_kobo:
        rules.append(("UNVERIFIED_HIGH_VALUE", "HIGH", 75,
                      [{"signal": "phone_not_verified", "price_kobo": price_kobo}]))
    if velocity_count >= settings.fraud_velocity_count:
        rules.append(("TRANSACTION_VELOCITY", "HIGH" if velocity_count >= settings.fraud_velocity_count * 2 else "MEDIUM",
                      min(95, 50 + velocity_count * 5), [{"signal": "transactions_in_window", "count": velocity_count,
                                                         "window_minutes": settings.fraud_velocity_window_min}]))
    return rules


async def scan_recent_transactions(db: AsyncSession, settings: Settings, *, lookback_minutes: int = 60) -> int:
    """Create review signals only. This never blocks, refunds, or changes transaction state."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=lookback_minutes)
    txns = list((await db.execute(
        select(Transaction, User.phone_verified_at).join(User, User.id == Transaction.user_id)
        .where(Transaction.created_at >= since, Transaction.status.in_(("INITIATED", "PENDING", "PROCESSING", "SUCCESSFUL", "UNKNOWN")))
        .order_by(Transaction.created_at.desc()).limit(5000)
    )).all())
    velocity_start = now - timedelta(minutes=settings.fraud_velocity_window_min)
    velocity_rows = (await db.execute(select(Transaction.user_id, func.count()).where(
        Transaction.created_at >= velocity_start,
        Transaction.status.not_in(("FAILED", "REVERSED", "REFUNDED")),
    ).group_by(Transaction.user_id))).all()
    velocity = {user_id: int(count) for user_id, count in velocity_rows}
    values = []
    for txn, verified_at in txns:
        count = velocity.get(txn.user_id, 0) if txn.created_at >= velocity_start else 0
        rules = evaluate_signals(txn.price_kobo, verified_at is not None, count, settings)
        for code, severity, score, reasons in rules:
            values.append({"transaction_id": txn.id, "user_id": txn.user_id, "rule_code": code,
                           "severity": severity, "score": min(100, score), "status": "OPEN", "reasons": reasons})
    created = 0
    if values:
        inserted = await db.execute(insert(FraudCase).values(values)
            .on_conflict_do_nothing(constraint="uq_fraud_cases_transaction_rule").returning(FraudCase.id))
        created = len(inserted.scalars().all())
    await db.commit()
    return created
