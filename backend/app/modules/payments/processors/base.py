import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class VerifyStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class InitResult:
    authorization_url: str
    access_code: str


@dataclass(frozen=True)
class Verification:
    status: VerifyStatus
    reference: str | None = None
    amount_kobo: int | None = None
    currency: str | None = None
    transaction_id: str | None = None
    paid_at: datetime | None = None
    # The processor's own charge for this payment, in kobo (None when it did not report one).
    # Informational only: it is deducted from the business's settlement, never from the customer.
    fees_kobo: int | None = None


class PaymentProcessor(Protocol):
    name: str

    async def initialize(self, *, reference: str, amount_kobo: int, email: str,
                         callback_url: str | None, metadata: dict[str, Any]) -> InitResult: ...

    async def verify(self, reference: str) -> Verification: ...

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool: ...


def hmac_sha512_hex(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()


def signature_matches(secret: str, raw_body: bytes, signature: str) -> bool:
    return bool(signature) and hmac.compare_digest(hmac_sha512_hex(secret, raw_body), signature.lower())
