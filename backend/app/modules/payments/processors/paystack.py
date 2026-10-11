import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from app.modules.payments.errors import ProcessorRejectedError, ProcessorUnavailableError
from app.modules.payments.processors.base import (
    InitResult, Verification, VerifyStatus, signature_matches,
)

log = logging.getLogger(__name__)
BASE_URL = "https://api.paystack.co"  # fixed: no user-controlled URLs, so no SSRF surface
_STATUS_MAP = {"success": VerifyStatus.SUCCESS, "failed": VerifyStatus.FAILED,
               "abandoned": VerifyStatus.ABANDONED, "reversed": VerifyStatus.REVERSED}
_VERIFY_ATTEMPTS = 3


class PaystackProcessor:
    name = "paystack"

    def __init__(self, client: httpx.AsyncClient, secret_key: str) -> None:
        self._client, self._secret = client, secret_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}"}

    async def initialize(self, *, reference: str, amount_kobo: int, email: str,
                         callback_url: str | None, metadata: dict[str, Any]) -> InitResult:
        body: dict[str, Any] = {"email": email, "amount": amount_kobo, "currency": "NGN",
                                "reference": reference, "metadata": metadata}
        if callback_url:
            body["callback_url"] = callback_url
        try:  # not auto-retried: a retry could create a second checkout session
            resp = await self._client.post(f"{BASE_URL}/transaction/initialize", json=body,
                                           headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProcessorUnavailableError(error=type(exc).__name__) from exc
        if resp.status_code >= 500 or resp.status_code in (401, 403, 429):
            log.error("paystack_initialize_unavailable", extra={"status": resp.status_code})
            raise ProcessorUnavailableError(status=resp.status_code)
        if resp.status_code >= 400:
            # Keep the provider's explanation for diagnosis without logging the request,
            # customer email, authorization headers, or full response body.
            try:
                provider_payload = resp.json()
                provider_message = provider_payload.get("message") if isinstance(provider_payload, dict) else None
            except ValueError:
                provider_message = None
            log.warning(
                "paystack_initialize_rejected",
                extra={
                    "status": resp.status_code,
                    "provider_message": str(provider_message)[:240] if provider_message else "no provider message",
                },
            )
            raise ProcessorRejectedError(status=resp.status_code)
        try:
            data = resp.json()["data"]
            return InitResult(str(data["authorization_url"]), str(data["access_code"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise ProcessorUnavailableError(error="bad_initialize_response") from exc

    async def verify(self, reference: str) -> Verification:
        """Safe to retry: it is a read."""
        last: Exception | None = None
        for attempt in range(_VERIFY_ATTEMPTS):
            if attempt:
                await asyncio.sleep(0.2 * 2 ** attempt)
            try:
                resp = await self._client.get(f"{BASE_URL}/transaction/verify/{reference}",
                                              headers=self._headers())
            except httpx.HTTPError as exc:
                last = exc
                continue
            if resp.status_code == 404:
                return Verification(VerifyStatus.NOT_FOUND, reference)
            if resp.status_code >= 500 or resp.status_code in (401, 403, 429):
                last = RuntimeError(f"status {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise ProcessorUnavailableError(status=resp.status_code)
            return self._parse(resp)
        raise ProcessorUnavailableError(error=str(last)) from last

    @staticmethod
    def _parse(resp: httpx.Response) -> Verification:
        try:
            data = resp.json()["data"]
            amount = data["amount"]
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise TypeError("amount must be an integer number of kobo")
            paid = data.get("paid_at")
            return Verification(
                status=_STATUS_MAP.get(str(data["status"]).lower(), VerifyStatus.PENDING),
                reference=str(data["reference"]), amount_kobo=amount,
                currency=str(data.get("currency", "")), transaction_id=str(data["id"]),
                paid_at=datetime.fromisoformat(paid.replace("Z", "+00:00")) if paid else None)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProcessorUnavailableError(error="bad_verify_response") from exc

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        return signature_matches(self._secret, raw_body, signature)
