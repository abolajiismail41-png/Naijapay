import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import uuid7
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.notifications.service import record_notification
from app.modules.ledger.interface import SystemAccount
from app.modules.payments.errors import (
    AmountOutOfRangeError, ProcessorRejectedError, ProcessorUnavailableError,
)
from app.modules.payments.fees import FundingFeePolicy
from app.modules.payments.models import Payment, PaymentStatus, WebhookEvent
from app.modules.payments.processors.base import PaymentProcessor, VerifyStatus
from app.modules.users.models import User
from app.modules.wallet.service import WalletService

log = logging.getLogger(__name__)
_FINAL = {PaymentStatus.SUCCESSFUL.value, PaymentStatus.MISMATCH.value}
_OPEN = (PaymentStatus.INITIATED.value, PaymentStatus.PENDING.value)


@dataclass(frozen=True)
class Quote:
    amount: Money
    fee: Money

    @property
    def total(self) -> Money:
        return self.amount + self.fee


def _now() -> datetime:
    return datetime.now(UTC)


class FundingService:
    """Wallet funding. Rule one: the wallet is credited only after the processor's own verify API
    confirms the payment. Webhook bodies, callback pages and the frontend are never trusted."""

    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings,
                 processor: PaymentProcessor) -> None:
        self.db, self.redis, self.settings, self.processor = db, redis, settings, processor
        self.fees = FundingFeePolicy.from_settings(settings)

    # ---------- quote / initiate ----------
    def quote(self, amount_kobo: int) -> Quote:
        s = self.settings
        if not s.funding_min_kobo <= amount_kobo <= s.funding_max_kobo:
            raise AmountOutOfRangeError(
                f"You can fund between NGN {Money(s.funding_min_kobo).naira:,.0f} "
                f"and NGN {Money(s.funding_max_kobo).naira:,.0f} at a time.")
        amount = Money(amount_kobo)
        return Quote(amount, self.fees.fee_for(amount))

    async def initiate(self, user: User, amount_kobo: int, idempotency_key: str) -> Payment:
        quote = self.quote(amount_kobo)
        await ratelimit.hit(self.redis, f"rl:fund:{user.id}", 10, 3600)
        req_hash = hashlib.sha256(f"fund:{amount_kobo}".encode()).hexdigest()
        reference = f"fnd_{uuid7().hex}"
        await self.db.execute(
            insert(Payment).values(
                id=uuid7(), user_id=user.id, reference=reference, processor=self.processor.name,
                status=PaymentStatus.INITIATED.value, amount_kobo=quote.amount.kobo,
                fee_kobo=quote.fee.kobo, charged_kobo=quote.total.kobo, idempotency_key=idempotency_key,
                request_hash=req_hash, attempts=0,
                expires_at=_now() + timedelta(hours=self.settings.funding_open_ttl_h))
            .on_conflict_do_nothing(constraint="uq_payments_user_idempotency"))
        payment = (await self.db.execute(
            select(Payment).where(Payment.user_id == user.id, Payment.idempotency_key == idempotency_key)
            .with_for_update())).scalar_one()
        if payment.request_hash != req_hash:
            await self.db.rollback()
            raise ConflictError("This idempotency key was already used with a different amount.")
        if payment.reference == reference:
            audit.record(self.db, action="payment.initiated", actor_user_id=user.id,
                         resource_type="payment", resource_id=payment.reference,
                         meta={"amount_kobo": quote.amount.kobo, "fee_kobo": quote.fee.kobo})
        if payment.status != PaymentStatus.INITIATED.value:
            await self.db.commit()
            return payment  # replay: same key returns the same checkout session and status
        # Only one request may run the processor handshake for a payment at a time; a concurrent
        # duplicate gets the current state back (INITIATED) and polls, so two checkout sessions can
        # never exist for one payment.
        lock_key = f"fund:init:{payment.id}"
        if not await self.redis.set(lock_key, 1, ex=15, nx=True):
            await self.db.commit()
            return payment
        try:
            # No checkout URL has ever been handed out, so a fresh processor reference is safe.
            payment.attempts += 1
            # Paystack references allow alphanumerics and selected punctuation, but not underscores.
            # Keep the internal fnd_ reference unchanged for our API; use a provider-safe reference.
            payment.processor_reference = f"fnd-{payment.reference[4:]}-{payment.attempts}"
            proc_ref = payment.processor_reference
            email = (user.email or "").strip().lower()
            if not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                await self.db.rollback()
                from app.core.errors import AppError
                raise AppError("Add a valid email address to your account before funding your wallet.")
            await self.db.commit()  # persist intent BEFORE calling out; never hold a lock during HTTP
            try:
                init = await self.processor.initialize(
                    reference=proc_ref, amount_kobo=quote.total.kobo, email=email,
                    callback_url=self.settings.paystack_callback_url,
                    metadata={"payment_reference": payment.reference, "purpose": "WALLET_FUNDING"})
            except ProcessorRejectedError:
                payment.status, payment.failure_reason = PaymentStatus.FAILED.value, "processor rejected initialize"
                await self.db.commit()
                raise
            # ProcessorUnavailableError propagates: outcome unknown, stays INITIATED, client retries.
            payment.status = PaymentStatus.PENDING.value
            payment.authorization_url, payment.access_code = init.authorization_url, init.access_code
            await self.db.commit()
            return payment
        finally:
            await self.redis.delete(lock_key)

    async def get_for_user(self, user_id: uuid.UUID, reference: str) -> Payment:
        p = (await self.db.execute(select(Payment).where(
            Payment.reference == reference, Payment.user_id == user_id))).scalar_one_or_none()
        if p is None:
            raise NotFoundError("Payment not found.")
        return p

    async def refresh_if_stale(self, payment: Payment) -> Payment:
        """Poll path: if the webhook has not arrived, ask the processor ourselves (rate-limited)."""
        if payment.status not in _OPEN or not payment.processor_reference:
            return payment
        age = (_now() - payment.updated_at).total_seconds()
        if age < self.settings.funding_poll_verify_after_s:
            return payment
        if not await self.redis.set(f"fund:poll:{payment.id}", 1, ex=5, nx=True):
            return payment
        try:
            return await self.settle(payment.id, source="poll")
        except ProcessorUnavailableError:
            await self.db.rollback()
            return payment

    # ---------- settlement ----------
    async def settle(self, payment_id: uuid.UUID, *, source: str) -> Payment:
        """Verify with the processor, then apply the outcome atomically. Safe to call from the
        webhook worker, the poll endpoint and the sweeper at the same time."""
        payment = await self.db.get(Payment, payment_id, populate_existing=True)
        if payment is None:
            raise NotFoundError("Payment not found.")
        if payment.status in _FINAL or not payment.processor_reference:
            return payment
        verification = await self.processor.verify(payment.processor_reference)  # may raise Unavailable

        # Lock payment before wallet, always, so purchase flows can follow the same order later.
        payment = (await self.db.execute(select(Payment).where(Payment.id == payment_id).with_for_update()
                                         .execution_options(populate_existing=True))).scalar_one()
        if payment.status in _FINAL:
            await self.db.commit()
            return payment
        now, v = _now(), verification
        previous_status = payment.status

        if v.status is VerifyStatus.SUCCESS:
            problems = []
            if v.reference != payment.processor_reference:
                problems.append("reference")
            if v.currency != payment.currency:
                problems.append("currency")
            if v.amount_kobo != payment.charged_kobo:
                problems.append("amount")
            if problems:
                payment.status = PaymentStatus.MISMATCH.value
                payment.failure_reason = f"mismatch: {','.join(problems)}"[:200]
                audit.record(self.db, action="payment.mismatch", actor_user_id=payment.user_id,
                             resource_type="payment", resource_id=payment.reference,
                             meta={"expected_kobo": payment.charged_kobo, "got_kobo": v.amount_kobo,
                                   "expected_currency": payment.currency, "got_currency": v.currency,
                                   "fields": problems, "source": source})
                await self.db.commit()
                return payment
            await WalletService(self.db).credit(
                payment.user_id, Money(payment.amount_kobo), fee=Money(payment.fee_kobo),
                reference=f"funding:{payment.reference}", kind="wallet.funding",
                source=SystemAccount.PROCESSOR_CLEARING, description="Wallet funding",
                meta={"payment_reference": payment.reference, "processor_reference": payment.processor_reference})
            payment.status = PaymentStatus.SUCCESSFUL.value
            payment.paid_at, payment.processor_txn_id = v.paid_at or now, v.transaction_id
            payment.journal_reference, payment.failure_reason = f"funding:{payment.reference}", None
            audit.record(self.db, action="payment.credited", actor_user_id=payment.user_id,
                         resource_type="payment", resource_id=payment.reference,
                         meta={"amount_kobo": payment.amount_kobo, "fee_kobo": payment.fee_kobo, "source": source})
            await record_notification(self.db, user_id=payment.user_id,
                event_key=f"payment:{payment.reference}:SUCCESSFUL", category="WALLET",
                title="Wallet funded", body=f"Your wallet has been credited with NGN {Money(payment.amount_kobo).naira_str()}.",
                resource_type="payment", resource_reference=payment.reference,
                payload={"status": "SUCCESSFUL", "amount_kobo": payment.amount_kobo})
        elif v.status in (VerifyStatus.FAILED, VerifyStatus.REVERSED):
            # FAILED can later become SUCCESSFUL: a customer may retry the card on the same session.
            if payment.status in _OPEN:
                payment.status, payment.failure_reason = PaymentStatus.FAILED.value, v.status.value.lower()
                audit.record(self.db, action="payment.failed", actor_user_id=payment.user_id,
                             resource_type="payment", resource_id=payment.reference, meta={"source": source})
        elif now >= payment.expires_at and payment.status in _OPEN:
            payment.status, payment.failure_reason = PaymentStatus.ABANDONED.value, "not completed in time"
        elif v.status is VerifyStatus.NOT_FOUND and payment.status == PaymentStatus.INITIATED.value \
                and now - payment.created_at > timedelta(minutes=10):
            payment.status, payment.failure_reason = PaymentStatus.FAILED.value, "checkout never created"
        if payment.status != previous_status and payment.status in (PaymentStatus.FAILED.value, PaymentStatus.ABANDONED.value):
            await record_notification(self.db, user_id=payment.user_id,
                event_key=f"payment:{payment.reference}:{payment.status}", category="WALLET",
                title="Wallet funding not completed",
                body="Your wallet was not credited. If your payment provider shows a debit, contact support with this reference.",
                resource_type="payment", resource_reference=payment.reference,
                payload={"status": payment.status})
        await self.db.commit()
        return payment

    # ---------- webhooks / sweeper ----------
    async def process_webhook_event(self, event_id: uuid.UUID) -> None:
        event = await self.db.get(WebhookEvent, event_id, populate_existing=True)
        if event is None or event.status in ("PROCESSED", "IGNORED"):
            return
        try:
            if event.event_type != "charge.success":
                await self._finish_event(event, "IGNORED")
                return
            ref = (event.payload.get("data") or {}).get("reference")
            payment = (await self.db.execute(select(Payment).where(Payment.processor_reference == ref))
                       ).scalar_one_or_none() if isinstance(ref, str) else None
            if payment is None:
                audit.record(self.db, action="payment.webhook_unknown_reference", meta={"reference": str(ref)[:80]})
                await self._finish_event(event, "IGNORED", "unknown reference")
                return
            await self.settle(payment.id, source="webhook")
            await self._finish_event(event, "PROCESSED")
        except ProcessorUnavailableError as exc:
            await self.db.rollback()
            event = await self.db.get(WebhookEvent, event_id, populate_existing=True)
            assert event is not None
            event.status, event.attempts, event.error = "FAILED", event.attempts + 1, exc.code
            await self.db.commit()
            raise

    async def _finish_event(self, event: WebhookEvent, status: str, error: str | None = None) -> None:
        event.status, event.processed_at, event.error = status, _now(), error
        await self.db.commit()

    async def sweep(self, limit: int = 100) -> int:
        """Safety net for lost webhooks, lost queue messages and abandoned checkouts."""
        done, now = 0, _now()
        events = (await self.db.execute(
            select(WebhookEvent.id).where(WebhookEvent.status.in_(("RECEIVED", "FAILED")),
                                          WebhookEvent.received_at < now - timedelta(minutes=1),
                                          WebhookEvent.attempts < 10)
            .order_by(WebhookEvent.received_at).limit(limit))).scalars().all()
        payments = (await self.db.execute(
            select(Payment.id).where(Payment.status.in_(_OPEN), Payment.created_at < now - timedelta(minutes=2))
            .order_by(Payment.created_at).limit(limit))).scalars().all()
        await self.db.rollback()
        for eid in events:
            try:
                await self.process_webhook_event(eid)
                done += 1
            except Exception:  # noqa: BLE001
                await self.db.rollback()
                log.warning("sweep_event_failed", extra={"event_id": str(eid)})
        for pid in payments:
            try:
                await self.settle(pid, source="sweep")
                done += 1
            except Exception:  # noqa: BLE001
                await self.db.rollback()
                log.warning("sweep_payment_failed", extra={"payment_id": str(pid)})
        return done
