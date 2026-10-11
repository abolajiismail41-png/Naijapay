"""In-memory stand-in for a processor: local development and tests only (refused in production)."""
from datetime import UTC, datetime
from typing import Any

from app.modules.payments.errors import ProcessorUnavailableError
from app.modules.payments.processors.base import (
    InitResult, Verification, VerifyStatus, signature_matches,
)


class SandboxProcessor:
    name = "sandbox"

    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret
        self.sessions: dict[str, dict[str, Any]] = {}
        self.initialize_calls = 0
        self.fail_initialize = False
        self.fail_verify = False

    async def initialize(self, *, reference: str, amount_kobo: int, email: str,
                         callback_url: str | None, metadata: dict[str, Any]) -> InitResult:
        self.initialize_calls += 1
        if self.fail_initialize:
            raise ProcessorUnavailableError(error="sandbox_timeout")
        self.sessions[reference] = {"amount_kobo": amount_kobo, "status": VerifyStatus.PENDING,
                                    "currency": "NGN", "txn_id": str(900000 + len(self.sessions))}
        return InitResult(f"https://sandbox.pay.local/checkout/{reference}", f"ac_{reference[-12:]}")

    def simulate(self, reference: str, *, status: VerifyStatus = VerifyStatus.SUCCESS,
                 amount_kobo: int | None = None, currency: str = "NGN") -> str:
        """Pretend the customer acted on the checkout page. Returns the processor transaction id."""
        s = self.sessions[reference]
        s.update(status=status, currency=currency)
        if amount_kobo is not None:
            s["amount_kobo"] = amount_kobo
        return str(s["txn_id"])

    async def verify(self, reference: str) -> Verification:
        if self.fail_verify:
            raise ProcessorUnavailableError(error="sandbox_verify_down")
        s = self.sessions.get(reference)
        if s is None:
            return Verification(VerifyStatus.NOT_FOUND, reference)
        paid = datetime.now(UTC) if s["status"] is VerifyStatus.SUCCESS else None
        return Verification(s["status"], reference, s["amount_kobo"], s["currency"], s["txn_id"], paid)

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        return signature_matches(self._secret, raw_body, signature)
