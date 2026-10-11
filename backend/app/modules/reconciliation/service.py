from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger.models import LedgerEntry, LedgerJournal
from app.modules.reconciliation.models import ReconciliationRecord, ReconciliationRun
from app.modules.transactions.models import Transaction
from app.modules.ledger.service import trial_balance_diff


async def run_internal_reconciliation(db: AsyncSession, *, actor_user_id=None) -> dict[str, Any]:
    """Read-only internal controls. External provider/bank statement matching is a separate feed integration."""
    now = datetime.now(timezone.utc)
    run = ReconciliationRun(run_type="INTERNAL_LEDGER", status="RUNNING", started_by_user_id=actor_user_id,
                            summary={"scope": "internal ledger and transaction references"})
    db.add(run)
    await db.flush()
    records: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    diff = await trial_balance_diff(db)
    checks.append({"code": "LEDGER_TRIAL_BALANCE", "ok": diff == 0, "difference_kobo": diff})
    if diff:
        records.append({"code": "LEDGER_TRIAL_BALANCE", "entity_type": "ledger", "entity_id": "all-accounts",
                        "classification": "UNBALANCED", "detail": {"debits_minus_credits_kobo": diff}})

    debit = func.coalesce(func.sum(case((LedgerEntry.direction == "D", LedgerEntry.amount_kobo), else_=0)), 0)
    credit = func.coalesce(func.sum(case((LedgerEntry.direction == "C", LedgerEntry.amount_kobo), else_=0)), 0)
    unbalanced = (await db.execute(select(LedgerJournal.id, LedgerJournal.reference, debit, credit)
        .join(LedgerEntry, LedgerEntry.journal_id == LedgerJournal.id)
        .group_by(LedgerJournal.id, LedgerJournal.reference)
        .having(debit != credit).limit(100))).all()
    checks.append({"code": "JOURNAL_BALANCE", "ok": not unbalanced, "sample_count": len(unbalanced), "sample_capped": len(unbalanced) == 100})
    for jid, reference, d, c in unbalanced:
        records.append({"code": "JOURNAL_BALANCE", "entity_type": "journal", "entity_id": str(jid),
                        "classification": "UNBALANCED", "detail": {"reference": reference,
                        "debits_kobo": int(d), "credits_kobo": int(c)}})

    missing_settle = list((await db.execute(select(Transaction.id, Transaction.reference, Transaction.status)
        .where(Transaction.status == "SUCCESSFUL", Transaction.settle_journal_reference.is_(None)).limit(100))).all())
    checks.append({"code": "SUCCESS_WITHOUT_SETTLEMENT", "ok": not missing_settle, "sample_count": len(missing_settle)})
    for tid, reference, status in missing_settle:
        records.append({"code": "SUCCESS_WITHOUT_SETTLEMENT", "entity_type": "transaction", "entity_id": str(tid),
                        "classification": "MISSING_INTERNAL", "detail": {"reference": reference, "status": status}})

    bad_settle = list((await db.execute(select(Transaction.id, Transaction.reference, Transaction.settle_journal_reference)
        .outerjoin(LedgerJournal, LedgerJournal.reference == Transaction.settle_journal_reference)
        .where(Transaction.status == "SUCCESSFUL", Transaction.settle_journal_reference.is_not(None), LedgerJournal.id.is_(None)).limit(100))).all())
    checks.append({"code": "SETTLEMENT_REFERENCE_MISSING", "ok": not bad_settle, "sample_count": len(bad_settle)})
    for tid, reference, journal_ref in bad_settle:
        records.append({"code": "SETTLEMENT_REFERENCE_MISSING", "entity_type": "transaction", "entity_id": str(tid),
                        "classification": "MISSING_INTERNAL", "detail": {"reference": reference, "journal_reference": journal_ref}})

    missing_refund = list((await db.execute(select(Transaction.id, Transaction.reference, Transaction.refund_journal_reference)
        .outerjoin(LedgerJournal, LedgerJournal.reference == Transaction.refund_journal_reference)
        .where(Transaction.status == "REFUNDED", Transaction.refund_journal_reference.is_(None)).limit(100))).all())
    checks.append({"code": "REFUND_WITHOUT_JOURNAL", "ok": not missing_refund, "sample_count": len(missing_refund)})
    for tid, reference, journal_ref in missing_refund:
        records.append({"code": "REFUND_WITHOUT_JOURNAL", "entity_type": "transaction", "entity_id": str(tid),
                        "classification": "MISSING_INTERNAL", "detail": {"reference": reference, "journal_reference": journal_ref}})

    bad_refund = list((await db.execute(select(Transaction.id, Transaction.reference, Transaction.refund_journal_reference)
        .outerjoin(LedgerJournal, LedgerJournal.reference == Transaction.refund_journal_reference)
        .where(Transaction.status == "REFUNDED", Transaction.refund_journal_reference.is_not(None), LedgerJournal.id.is_(None)).limit(100))).all())
    checks.append({"code": "REFUND_REFERENCE_MISSING", "ok": not bad_refund, "sample_count": len(bad_refund)})
    for tid, reference, journal_ref in bad_refund:
        records.append({"code": "REFUND_REFERENCE_MISSING", "entity_type": "transaction", "entity_id": str(tid),
                        "classification": "MISSING_INTERNAL", "detail": {"reference": reference, "journal_reference": journal_ref}})

    stuck_before = now - timedelta(minutes=30)
    stuck = list((await db.execute(select(Transaction.id, Transaction.reference, Transaction.status, Transaction.updated_at)
        .where(Transaction.status.in_(("INITIATED", "PENDING", "PROCESSING", "UNKNOWN")),
               Transaction.updated_at < stuck_before).order_by(Transaction.updated_at).limit(100))).all())
    checks.append({"code": "STUCK_TRANSACTIONS", "ok": not stuck, "sample_count": len(stuck)})
    for tid, reference, status, updated_at in stuck:
        records.append({"code": "STUCK_TRANSACTIONS", "entity_type": "transaction", "entity_id": str(tid),
                        "classification": "STUCK_PENDING", "detail": {"reference": reference, "status": status,
                        "updated_at": updated_at.isoformat() if updated_at else None}})

    for item in records:
        db.add(ReconciliationRecord(run_id=run.id, **item))
    run.status = "CLEAN" if all(c["ok"] for c in checks) else "ISSUES"
    run.finished_at = now
    run.summary = {"scope": "internal ledger and transaction references", "checks": checks,
                   "issue_count": len(records), "records_capped_per_check": 100,
                   "note": "This run does not compare provider or bank statements; external feeds are not configured."}
    await db.commit()
    return {"id": str(run.id), "run_type": run.run_type, "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else now.isoformat(),
            "finished_at": now.isoformat(), **run.summary}
