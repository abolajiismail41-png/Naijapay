import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit import CircuitBreaker
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.notifications.service import record_notification
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import Direction, EntryLine, SystemAccount
from app.modules.payments.models import WebhookEvent
from app.core.crypto import encrypt
from app.modules.providers.base import (
    AirtimeRequest, BillProvider, DataRequest, EducationRequest, ElectricityRequest, Outcome, ProviderResult, TVRequest,
)
from app.modules.providers.models import ProviderTransaction
from app.modules.services.models import PricingSnapshot
from app.modules.transactions.models import AirtimeOrder, DataOrder, EducationOrder, ElectricityOrder, TVOrder, Transaction
from app.modules.transactions.state import SETTLED, TxnStatus, transition
from app.modules.wallet.service import WalletService

log = logging.getLogger(__name__)
_STALE_PROCESSING_S, _INFLIGHT_LOST_S, _ESCALATE_AFTER = 20, 120, timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(UTC)


class TransactionService:
    """Runs the provider side of a purchase. Rules: persist PROCESSING before calling out; never retry a
    purchase; only a definite FAILED from the provider refunds; anything ambiguous stays UNKNOWN."""

    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings, providers: dict[str, BillProvider]) -> None:
        self.db, self.redis, self.settings, self.providers = db, redis, settings, providers

    async def _lock(self, txn_id: uuid.UUID) -> Transaction:
        q = select(Transaction).where(Transaction.id == txn_id).with_for_update().execution_options(populate_existing=True)
        txn = (await self.db.execute(q)).scalar_one_or_none()
        if txn is None:
            raise NotFoundError("Transaction not found.")
        return txn

    async def _log_call(self, txn: Transaction, call: str, request_id: str, r: ProviderResult, started: float) -> None:
        self.db.add(ProviderTransaction(
            transaction_id=txn.id, provider_code=txn.provider_code, call=call, request_id=request_id,
            provider_reference=r.provider_reference, outcome=r.outcome.value, http_status=r.http_status,
            latency_ms=int((time.monotonic() - started) * 1000), message=r.message[:200]))
        await self.db.commit()

    # ---------- send ----------
    async def execute(self, txn_id: uuid.UUID) -> Transaction:
        txn = await self._lock(txn_id)
        # SMS-Man Virtual Numbers are orchestrated by their dedicated adapter, not bill providers.
        if txn.service_type == "VNUMBER":
            await self.db.commit()
            return txn
        if txn.status != TxnStatus.PENDING.value:
            await self.db.commit()
            return txn
        provider = self.providers[txn.provider_code]
        breaker = CircuitBreaker(self.redis, f"provider:{txn.provider_code}")
        if await breaker.is_open():  # provider known to be down; nothing was sent, so waiting is safe
            txn.attempts += 1
            await self.db.commit()
            return txn
        order = await self.db.get({"AIRTIME": AirtimeOrder, "DATA": DataOrder, "ELECTRICITY": ElectricityOrder,
                                  "EDUCATION": EducationOrder, "TV": TVOrder}[txn.service_type], txn.id)
        assert order is not None
        req: AirtimeRequest | DataRequest | ElectricityRequest | EducationRequest | TVRequest
        if isinstance(order, AirtimeOrder):
            req = AirtimeRequest(txn.reference, txn.provider_service_id, order.network, "0" + order.phone[4:], Money(txn.amount_kobo))
        elif isinstance(order, DataOrder):
            req = DataRequest(txn.reference, txn.provider_service_id, order.network, "0" + order.phone[4:])
        elif isinstance(order, EducationOrder):
            req = EducationRequest(txn.reference, txn.provider_service_id, order.quantity)
        elif isinstance(order, ElectricityOrder):
            req = ElectricityRequest(txn.reference, txn.provider_service_id, order.provider_disco_code, order.meter_type,
                                     order.meter_number, Money(txn.amount_kobo))
        else:
            req = TVRequest(txn.reference, txn.provider_service_id, order.smartcard_number)
        transition(self.db, txn, TxnStatus.PROCESSING, "sending to provider")
        txn.sent_at, txn.attempts = _now(), txn.attempts + 1
        await self.db.commit()  # PROCESSING is durable BEFORE the call: a crash now can never look unsent
        started = time.monotonic()
        try:
            result = await (provider.purchase_airtime(req) if isinstance(req, AirtimeRequest)
                            else provider.purchase_data(req) if isinstance(req, DataRequest)
                            else provider.purchase_electricity(req) if isinstance(req, ElectricityRequest)
                            else provider.purchase_education(req) if isinstance(req, EducationRequest)
                            else provider.purchase_tv(req))
        except Exception as exc:  # noqa: BLE001  an adapter bug is an unknown outcome, never a failure
            log.exception("provider_adapter_error")
            result = ProviderResult(Outcome.UNKNOWN, message=f"adapter_error:{type(exc).__name__}")
        await self._log_call(txn, "PURCHASE", txn.reference, result, started)
        await (breaker.record_failure() if result.outcome is Outcome.UNKNOWN else breaker.record_success())
        return await self.apply(txn_id, result, source="execute")

    async def verify(self, txn_id: uuid.UUID) -> Transaction:
        txn = await self.db.get(Transaction, txn_id, populate_existing=True)
        if txn is not None and txn.service_type == "VNUMBER":
            return txn
        if txn is None or not txn.provider_reference or txn.status not in (
                TxnStatus.PROCESSING.value, TxnStatus.UNKNOWN.value, TxnStatus.REFUNDED.value, TxnStatus.FAILED.value):
            return txn  # type: ignore[return-value]
        started = time.monotonic()
        result = await self.providers[txn.provider_code].fetch_status(txn.provider_reference)
        await self._log_call(txn, "STATUS", txn.reference, result, started)
        return await self.apply(txn_id, result, source="verify")

    # ---------- apply an outcome ----------
    async def apply(self, txn_id: uuid.UUID, r: ProviderResult, *, source: str) -> Transaction:
        txn = await self._lock(txn_id)
        if r.provider_reference and not txn.provider_reference:
            txn.provider_reference = r.provider_reference[:80]
        st = TxnStatus(txn.status)
        if st in SETTLED:
            if r.outcome is Outcome.SUCCESS and st in (TxnStatus.REFUNDED, TxnStatus.FAILED):
                audit.record(self.db, action="transaction.late_success_after_refund", resource_type="transaction",
                             resource_id=txn.reference, meta={"source": source})  # customer refunded AND delivered
            elif r.outcome is Outcome.SUCCESS and r.token and st is TxnStatus.SUCCESSFUL and txn.service_type == "ELECTRICITY":
                order = await self.db.get(ElectricityOrder, txn.id)
                if order is not None and order.token_status == "MISSING":
                    self._store_token(order, txn, r)
                    audit.record(self.db, action="transaction.token_recovered", resource_type="transaction",
                                 resource_id=txn.reference, meta={"source": source})
            elif r.outcome is Outcome.SUCCESS and r.pins and st is TxnStatus.SUCCESSFUL and txn.service_type == "EDUCATION":
                eo = await self.db.get(EducationOrder, txn.id)
                if eo is not None and eo.pins_status in ("MISSING", "PARTIAL") and len(r.pins) > eo.pins_count:
                    self._store_pins(eo, txn, r)
                    audit.record(self.db, action="transaction.pins_recovered", resource_type="transaction",
                                 resource_id=txn.reference, meta={"source": source})
            elif r.outcome is Outcome.FAILED and st is TxnStatus.SUCCESSFUL:
                audit.record(self.db, action="transaction.late_failure_after_success", resource_type="transaction",
                             resource_id=txn.reference, meta={"source": source})
            await self.db.commit()
            return txn
        if st not in (TxnStatus.PROCESSING, TxnStatus.UNKNOWN):
            await self.db.commit()
            return txn
        if r.outcome is Outcome.SUCCESS:
            await self._succeed(txn, r, source)
        elif r.outcome is Outcome.FAILED:
            await self._fail_and_refund(txn, r.message or "provider declined", source)
        elif r.outcome is Outcome.PROCESSING:
            if st is TxnStatus.UNKNOWN:
                transition(self.db, txn, TxnStatus.PROCESSING, "provider reports processing")
            self._schedule_check(txn)
        else:
            if st is TxnStatus.PROCESSING:
                transition(self.db, txn, TxnStatus.UNKNOWN, r.message or "outcome unknown")
            self._schedule_check(txn)
        if txn.status != st.value and txn.status in (TxnStatus.SUCCESSFUL.value, TxnStatus.REFUNDED.value, TxnStatus.UNKNOWN.value):
            messages = {
                TxnStatus.SUCCESSFUL.value: ("Purchase successful", f"Your {txn.service_type.lower()} purchase is confirmed."),
                TxnStatus.REFUNDED.value: ("Purchase refunded", "Your purchase failed and the funds have been returned to your wallet."),
                TxnStatus.UNKNOWN.value: ("Purchase is being verified", "The provider has not confirmed the outcome yet. Please do not retry; we are checking it."),
            }
            title, body = messages[txn.status]
            await record_notification(self.db, user_id=txn.user_id,
                event_key=f"transaction:{txn.reference}:{txn.status}", category="TRANSACTION",
                title=title, body=body, resource_type="transaction", resource_reference=txn.reference,
                payload={"status": txn.status, "service": txn.service_type})
        await self.db.commit()
        return txn

    def _schedule_check(self, txn: Transaction) -> None:
        txn.verify_attempts += 1
        txn.next_check_at = (_now() + timedelta(seconds=min(30 * 2 ** txn.verify_attempts, 1800))
                             if txn.provider_reference else None)

    async def _succeed(self, txn: Transaction, r: ProviderResult, source: str) -> None:
        snap = await self.db.get(PricingSnapshot, txn.id)
        assert snap is not None
        cost = r.amount_charged if r.amount_charged and r.amount_charged.is_positive() else Money(snap.cost_kobo)
        # Exam pins: the provider's `amount` semantics (total vs per pin) are unverified, so a reported cost more than
        # 25% away from the quote is not trusted; we book the quoted cost and flag it for review.
        untrusted = txn.service_type == "EDUCATION" and abs(cost.kobo - snap.cost_kobo) * 4 > snap.cost_kobo
        if untrusted:
            cost = Money(snap.cost_kobo)
        price, discount, fee = Money(txn.price_kobo), Money(snap.discount_kobo), Money(snap.fee_kobo)
        revenue = price + discount - fee                      # list price less the fee, recognised as sales revenue
        referral = Money(snap.referral_commission_kobo)
        acct = {a: await ledger.system_account_id(self.db, a) for a in SystemAccount}
        D, C = Direction.DEBIT, Direction.CREDIT
        lines = [EntryLine(acct[SystemAccount.PROVIDER_CLEARING], D, price),   # release the customer's held funds
                 EntryLine(acct[SystemAccount.REVENUE], C, revenue),
                 EntryLine(acct[SystemAccount.PROVIDER_COST], D, cost),
                 EntryLine(acct[SystemAccount.PROVIDER_FLOAT], C, cost)]
        if discount.is_positive():
            lines.append(EntryLine(acct[SystemAccount.DISCOUNTS], D, discount))
        if fee.is_positive():
            lines.append(EntryLine(acct[SystemAccount.SERVICE_FEES], C, fee))
        if referral.is_positive():
            lines += [EntryLine(acct[SystemAccount.REFERRAL_EXPENSE], D, referral),
                      EntryLine(acct[SystemAccount.REFERRAL_PAYABLE], C, referral)]
        posted = await ledger.post_journal(self.db, reference=f"settle:{txn.reference}", kind="purchase.settlement",
                                           lines=lines, description="Airtime sale", meta={"transaction": txn.reference})
        txn.settle_journal_reference, txn.provider_cost_kobo = f"settle:{txn.reference}", cost.kobo
        transition(self.db, txn, TxnStatus.SUCCESSFUL, f"confirmed via {source}")
        from app.modules.referrals.service import reward_referrer_for_transaction
        await reward_referrer_for_transaction(self.db, txn, self.settings)
        await self._deliver_secret(txn, r)
        flags = ["cost_untrusted"] if untrusted else []
        if price + discount < cost:
            flags.append("negative_margin")
        if abs(cost.kobo - snap.cost_kobo) * 100 > max(snap.cost_kobo, 1):   # >1% away from the quoted cost
            flags.append("cost_variance")
        if txn.service_type == "AIRTIME" and r.amount and r.amount.kobo != txn.amount_kobo:
            flags.append("delivered_amount_mismatch")
        if r.amount_charged is None:
            flags.append("cost_estimated")
        if flags:
            audit.record(self.db, action="transaction.settlement_flags", resource_type="transaction",
                         resource_id=txn.reference, meta={"flags": flags, "cost_kobo": cost.kobo,
                                                          "quoted_cost_kobo": snap.cost_kobo, "journal": str(posted.id)})

    def _store_token(self, order: ElectricityOrder, txn: Transaction, r: ProviderResult) -> None:
        assert r.token
        order.token_ciphertext = encrypt(self.settings.encryption_key.get_secret_value(), r.token, txn.reference)
        order.units, order.token_status, order.token_delivered_at = r.units, "DELIVERED", _now()

    def _store_pins(self, order: EducationOrder, txn: Transaction, r: ProviderResult) -> None:
        assert r.pins
        blob = json.dumps([{"pin": p, "serial": sn} for p, sn in r.pins])
        order.pins_ciphertext = encrypt(self.settings.encryption_key.get_secret_value(), blob, txn.reference)
        order.pins_count = len(r.pins)
        order.pins_status = "DELIVERED" if len(r.pins) >= order.quantity else "PARTIAL"
        order.pins_delivered_at = _now()

    async def _deliver_secret(self, txn: Transaction, r: ProviderResult) -> None:
        """The sale is settled whatever happens here: a missing secret is flagged and recovered, never refunded."""
        if txn.service_type == "ELECTRICITY":
            order = await self.db.get(ElectricityOrder, txn.id)
            if order is None:
                return
            if order.meter_type != "PREPAID":
                order.token_status = "NOT_APPLICABLE"
            elif r.token:
                self._store_token(order, txn, r)
            else:
                order.token_status = "MISSING"
                audit.record(self.db, action="transaction.token_missing", resource_type="transaction", resource_id=txn.reference)
        elif txn.service_type == "EDUCATION":
            eo = await self.db.get(EducationOrder, txn.id)
            if eo is None:
                return
            if r.pins:
                self._store_pins(eo, txn, r)
                if eo.pins_status == "PARTIAL":
                    audit.record(self.db, action="transaction.pins_partial", resource_type="transaction", resource_id=txn.reference,
                                 meta={"received": eo.pins_count, "expected": eo.quantity})
            else:
                eo.pins_status = "MISSING"
                audit.record(self.db, action="transaction.pins_missing", resource_type="transaction", resource_id=txn.reference)

    async def recover_secret(self, txn_id: uuid.UUID) -> None:
        txn = await self._lock(txn_id)
        order: ElectricityOrder | EducationOrder | None = await self.db.get(
            ElectricityOrder if txn.service_type == "ELECTRICITY" else EducationOrder, txn_id)
        pending = order is not None and (
            order.token_status == "MISSING" if isinstance(order, ElectricityOrder) else order.pins_status in ("MISSING", "PARTIAL"))
        if not (pending and txn.status == TxnStatus.SUCCESSFUL.value and txn.provider_reference):
            await self.db.commit()
            return
        if txn.verify_attempts >= 12:
            if txn.escalated_at is None:
                txn.escalated_at = _now()
                audit.record(self.db, action="transaction.secret_unrecoverable", resource_type="transaction", resource_id=txn.reference)
            await self.db.commit()
            return
        txn.verify_attempts += 1
        txn.next_check_at = _now() + timedelta(seconds=min(60 * 2 ** txn.verify_attempts, 1800))
        ref, started = txn.provider_reference, time.monotonic()
        await self.db.commit()
        result = await self.providers[txn.provider_code].fetch_status(ref)
        await self._log_call(txn, "STATUS", txn.reference, result, started)
        await self.apply(txn_id, result, source="secret-recovery")

    async def _fail_and_refund(self, txn: Transaction, reason: str, source: str) -> None:
        transition(self.db, txn, TxnStatus.FAILED, reason)
        txn.failure_reason = reason[:200]
        mv = await WalletService(self.db).reverse(txn.hold_journal_reference or "", reference=f"refund:{txn.reference}",
                                                  reason="Purchase failed")
        txn.refund_journal_reference = mv.reference
        transition(self.db, txn, TxnStatus.REFUNDED, "held funds returned to wallet")
        audit.record(self.db, action="transaction.refunded", actor_user_id=txn.user_id, resource_type="transaction",
                     resource_id=txn.reference, meta={"source": source})

    # ---------- unsent / manual ----------
    async def fail_unsent(self, txn_id: uuid.UUID) -> None:
        txn = await self._lock(txn_id)
        if txn.status == TxnStatus.PENDING.value:  # PROCESSING is persisted before any call, so PENDING == never sent
            await self._fail_and_refund(txn, "provider unavailable; purchase was never sent", "sweep")
        await self.db.commit()

    async def resolve_manually(self, reference: str, *, actor_id: uuid.UUID, outcome: str, note: str,
                               cost_kobo: int | None = None, provider_reference: str | None = None,
                               token: str | None = None, pins: list[tuple[str, str]] | None = None) -> Transaction:
        txn = (await self.db.execute(select(Transaction).where(Transaction.reference == reference))).scalar_one_or_none()
        if txn is None:
            raise NotFoundError("Transaction not found.")
        txn = await self._lock(txn.id)
        if txn.status not in (TxnStatus.UNKNOWN.value, TxnStatus.PROCESSING.value):
            raise ConflictError("Only transactions awaiting a provider result can be resolved manually.")
        audit.record(self.db, action="transaction.manual_resolution", actor_user_id=actor_id, resource_type="transaction",
                     resource_id=txn.reference, before={"status": txn.status},
                     after={"outcome": outcome, "cost_kobo": cost_kobo}, meta={"note": note[:200]})
        res = ProviderResult(Outcome.SUCCESS if outcome == "SUCCESS" else Outcome.FAILED, provider_reference,
                             amount_charged=Money(cost_kobo) if cost_kobo else None, message=f"manual: {note}", token=token,
                             pins=tuple(pins) if pins else None)
        return await self.apply(txn.id, res, source="manual")

    # ---------- webhooks ----------
    async def process_provider_webhook(self, event_id: uuid.UUID) -> None:
        event = await self.db.get(WebhookEvent, event_id, populate_existing=True)
        if event is None or event.status in ("PROCESSED", "IGNORED"):
            return
        ref = (event.payload.get("data") or {}).get("reference")
        txn = (await self.db.execute(select(Transaction).where(
            Transaction.provider_reference == str(ref)))).scalar_one_or_none() if ref else None
        if txn is None:
            event.status, event.attempts, event.error = "FAILED", event.attempts + 1, "no matching transaction yet"
            await self.db.commit()
            return
        await self.verify(txn.id)  # the body is only a hint: the status comes from the provider's API
        event.status, event.processed_at, event.error = "PROCESSED", _now(), None
        await self.db.commit()

    # ---------- safety net ----------
    async def sweep(self, limit: int = 100) -> int:
        now, done = _now(), 0
        unsent_cut = now - timedelta(minutes=self.settings.unsent_refund_after_min)
        pending = (await self.db.execute(select(Transaction.id, Transaction.created_at).where(
            Transaction.status == "PENDING", Transaction.updated_at < now - timedelta(seconds=30))
            .order_by(Transaction.created_at).limit(limit))).all()
        processing = (await self.db.execute(select(Transaction.id, Transaction.provider_reference, Transaction.sent_at).where(
            Transaction.status == "PROCESSING", Transaction.sent_at < now - timedelta(seconds=_STALE_PROCESSING_S))
            .limit(limit))).all()
        unknown = (await self.db.execute(select(Transaction.id, Transaction.provider_reference, Transaction.next_check_at,
                                                Transaction.escalated_at, Transaction.sent_at)
                                         .where(Transaction.status == "UNKNOWN").limit(limit))).all()
        due = (Transaction.completed_at < now - timedelta(minutes=1), Transaction.escalated_at.is_(None),
               (Transaction.next_check_at.is_(None)) | (Transaction.next_check_at <= now))
        missing_tokens = list((await self.db.execute(
            select(Transaction.id).join(ElectricityOrder, ElectricityOrder.transaction_id == Transaction.id).where(
                Transaction.status == "SUCCESSFUL", ElectricityOrder.token_status == "MISSING", *due).limit(limit))).scalars())
        missing_tokens += list((await self.db.execute(
            select(Transaction.id).join(EducationOrder, EducationOrder.transaction_id == Transaction.id).where(
                Transaction.status == "SUCCESSFUL", EducationOrder.pins_status.in_(("MISSING", "PARTIAL")), *due).limit(limit))).scalars())
        events = (await self.db.execute(select(WebhookEvent.id).where(
            WebhookEvent.source == "inlomax", WebhookEvent.status.in_(("RECEIVED", "FAILED")),
            WebhookEvent.received_at < now - timedelta(minutes=1), WebhookEvent.attempts < 10).limit(limit))).scalars().all()
        await self.db.rollback()
        jobs: list[tuple[str, uuid.UUID]] = []
        for tid, created in pending:
            jobs.append(("unsent" if created < unsent_cut else "execute", tid))
        for tid, ref, sent in processing:
            if ref:
                jobs.append(("verify", tid))
            elif sent and sent < now - timedelta(seconds=_INFLIGHT_LOST_S):
                jobs.append(("lost", tid))   # call was in flight when we lost track: outcome unknown, NOT failed
        for tid, ref, nxt, esc, sent in unknown:
            if ref and (nxt is None or nxt <= now):
                jobs.append(("verify", tid))
            elif not ref and esc is None and sent and sent < now - _ESCALATE_AFTER:
                jobs.append(("escalate", tid))
        jobs += [("token", tid) for tid in missing_tokens]
        for kind, tid in jobs:
            try:
                if kind == "execute":
                    await self.execute(tid)
                elif kind == "unsent":
                    await self.fail_unsent(tid)
                elif kind == "verify":
                    await self.verify(tid)
                elif kind == "token":
                    await self.recover_secret(tid)
                elif kind == "lost":
                    await self.apply(tid, ProviderResult(Outcome.UNKNOWN, message="in-flight call lost"), source="sweep")
                else:
                    await self._escalate(tid)
                done += 1
            except Exception:  # noqa: BLE001
                await self.db.rollback()
                log.warning("sweep_job_failed", extra={"kind": kind, "txn": str(tid)})
        for eid in events:
            try:
                await self.process_provider_webhook(eid)
                done += 1
            except Exception:  # noqa: BLE001
                await self.db.rollback()
        return done

    async def _escalate(self, txn_id: uuid.UUID) -> None:
        txn = await self._lock(txn_id)
        if txn.status == TxnStatus.UNKNOWN.value and txn.escalated_at is None:
            txn.escalated_at = _now()
            audit.record(self.db, action="transaction.unknown_unresolvable", resource_type="transaction",
                         resource_id=txn.reference,
                         meta={"why": "no provider reference; the provider API cannot be queried by request-id"})
        await self.db.commit()
