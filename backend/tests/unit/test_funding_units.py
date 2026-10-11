import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.core.money import Money
from app.modules.payments.errors import ProcessorRejectedError, ProcessorUnavailableError
from app.modules.payments.fees import FundingFeePolicy
from app.modules.payments.processors.base import VerifyStatus
from app.modules.payments.processors.paystack import PaystackProcessor


def _policy() -> FundingFeePolicy:
    s = Settings(_env_file=None, environment="test", database_url="x", redis_url="y",
                 jwt_secret="a", encryption_key="b", webhook_secret="c")
    return FundingFeePolicy.from_settings(s)


def test_fee_policy_matches_published_paystack_shape() -> None:
    p = _policy()
    assert p.fee_for(Money.from_naira(500)) == Money.from_naira("7.50")        # flat waived under 2,500
    assert p.fee_for(Money.from_naira(2499)) == Money(3748)                    # 1.5% only, half-even rounding of 3748.5 kobo
    assert p.fee_for(Money.from_naira(5000)) == Money.from_naira("175.00")     # 75 + 100 flat
    assert p.fee_for(Money.from_naira(2_000_000)) == Money.from_naira(2000)    # capped


def test_fee_is_deterministic_and_integer() -> None:
    p = _policy()
    assert p.fee_for(Money(333_333)) == p.fee_for(Money(333_333))
    assert isinstance(p.fee_for(Money(333_333)).kobo, int)


def test_production_requires_paystack_and_real_key() -> None:
    strong = "x" * 40
    base = dict(environment="production", database_url="x", redis_url="y", jwt_secret=strong,
                encryption_key=strong, webhook_secret=strong, cors_origins=["https://a.example"])
    with pytest.raises(ValueError):
        Settings(_env_file=None, **base)  # sandbox processor
    with pytest.raises(ValueError):
        Settings(_env_file=None, payment_processor="paystack", paystack_secret_key="", **base)
    with pytest.raises(ValueError):
        Settings(_env_file=None, payment_processor="paystack", paystack_secret_key="sk_live_abc", **base)  # sandbox bills
    Settings(_env_file=None, payment_processor="paystack", paystack_secret_key="sk_live_abc", bill_provider="inlomax",
             inlomax_api_key="k", inlomax_webhook_token="w" * 40, **base)


def _client(handler) -> PaystackProcessor:
    return PaystackProcessor(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "sk_test_secret")


async def test_initialize_sends_kobo_integer_and_bearer_auth() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"], seen["body"], seen["url"] = req.headers["authorization"], json.loads(req.content), str(req.url)
        return httpx.Response(200, json={"status": True, "data": {"authorization_url": "https://x/y", "access_code": "ac"}})

    r = await _client(handler).initialize(reference="r1", amount_kobo=507500, email="a@b.c",
                                          callback_url="https://cb", metadata={"k": "v"})
    assert r.authorization_url == "https://x/y"
    assert seen["auth"] == "Bearer sk_test_secret" and seen["url"].endswith("/transaction/initialize")
    assert seen["body"]["amount"] == 507500 and isinstance(seen["body"]["amount"], int)
    assert seen["body"]["currency"] == "NGN" and seen["body"]["reference"] == "r1"


async def test_initialize_error_mapping() -> None:
    with pytest.raises(ProcessorUnavailableError):
        await _client(lambda r: httpx.Response(503)).initialize(
            reference="r", amount_kobo=1, email="a@b.c", callback_url=None, metadata={})
    with pytest.raises(ProcessorRejectedError):
        await _client(lambda r: httpx.Response(400, json={"status": False})).initialize(
            reference="r", amount_kobo=1, email="a@b.c", callback_url=None, metadata={})

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("t")
    with pytest.raises(ProcessorUnavailableError):
        await _client(boom).initialize(reference="r", amount_kobo=1, email="a@b.c", callback_url=None, metadata={})


def _verify_body(status: str, amount: object = 507500) -> dict:
    return {"status": True, "data": {"id": 42, "status": status, "reference": "r1", "amount": amount,
                                     "currency": "NGN", "paid_at": "2026-10-04T10:00:00.000Z"}}


@pytest.mark.parametrize("raw,expected", [("success", VerifyStatus.SUCCESS), ("failed", VerifyStatus.FAILED),
                                          ("abandoned", VerifyStatus.ABANDONED), ("reversed", VerifyStatus.REVERSED),
                                          ("ongoing", VerifyStatus.PENDING), ("queued", VerifyStatus.PENDING)])
async def test_verify_status_mapping(raw: str, expected: VerifyStatus) -> None:
    v = await _client(lambda r: httpx.Response(200, json=_verify_body(raw))).verify("r1")
    assert v.status is expected and v.amount_kobo == 507500 and v.transaction_id == "42"


async def test_verify_404_is_not_found_and_5xx_is_unknown_never_failed() -> None:
    assert (await _client(lambda r: httpx.Response(404)).verify("r1")).status is VerifyStatus.NOT_FOUND
    with pytest.raises(ProcessorUnavailableError):
        await _client(lambda r: httpx.Response(500)).verify("r1")


async def test_verify_retries_transient_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502) if calls["n"] < 3 else httpx.Response(200, json=_verify_body("success"))

    assert (await _client(handler).verify("r1")).status is VerifyStatus.SUCCESS and calls["n"] == 3


@pytest.mark.parametrize("bad", [507500.0, "507500", True, None])
async def test_verify_rejects_non_integer_amounts(bad: object) -> None:
    with pytest.raises(ProcessorUnavailableError):
        await _client(lambda r: httpx.Response(200, json=_verify_body("success", bad))).verify("r1")


def test_webhook_signature_is_hmac_sha512_constant_time() -> None:
    p = _client(lambda r: httpx.Response(200))
    raw = b'{"event":"charge.success"}'
    good = hmac.new(b"sk_test_secret", raw, hashlib.sha512).hexdigest()
    assert p.verify_webhook_signature(raw, good) and p.verify_webhook_signature(raw, good.upper())
    assert not p.verify_webhook_signature(raw + b" ", good)
    assert not p.verify_webhook_signature(raw, "") and not p.verify_webhook_signature(raw, "deadbeef")
