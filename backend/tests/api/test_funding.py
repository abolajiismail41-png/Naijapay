import asyncio
import hashlib
import hmac
import json
import uuid

from sqlalchemy import text

from app.core.money import Money
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import SystemAccount
from app.modules.payments.errors import ProcessorUnavailableError
from app.modules.payments.processors.base import VerifyStatus
from app.modules.payments.service import FundingService
from app.modules.wallet.service import WalletService
from tests.api.helpers import audit_actions, bearer, signup

F = "/api/v1/wallet/funding"
AMOUNT = 500_000          # NGN 5,000.00
FEE, TOTAL = 17_500, 517_500   # 1.5% (7,500) + NGN 100 flat (10,000) = NGN 175.00


def sign(raw: bytes, secret: str = "test-webhook-secret") -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()


async def start(env, tokens, amount: int = AMOUNT, key: str | None = None):
    return await env.client.post(F, json={"amount_kobo": amount}, headers={
        **bearer(tokens), "Idempotency-Key": key or uuid.uuid4().hex})


async def pay_ref(env, ref: str) -> str:
    async with env.app.state.session_factory() as s:
        return (await s.execute(text("SELECT processor_reference FROM payments WHERE reference=:r"), {"r": ref})).scalar_one()


async def send_webhook(env, proc_ref: str, txn_id: int = 1001, *, signature: str | None = None,
                       event: str = "charge.success", amount: int = TOTAL):
    raw = json.dumps({"event": event, "data": {"id": txn_id, "reference": proc_ref, "amount": amount,
                                               "currency": "NGN", "status": "success"}}).encode()
    return await env.client.post("/api/v1/webhooks/paystack", content=raw, headers={
        "x-paystack-signature": signature if signature is not None else sign(raw),
        "content-type": "application/json"})


def service(env, s) -> FundingService:
    return FundingService(s, env.redis, env.app.state.settings, env.app.state.payment_processor)


async def event_ids(env) -> list[uuid.UUID]:
    async with env.app.state.session_factory() as s:
        return list((await s.execute(text("SELECT id FROM webhook_events ORDER BY received_at"))).scalars())


async def process(env, event_id) -> None:
    async with env.app.state.session_factory() as s:
        await service(env, s).process_webhook_event(event_id)


async def payment_id(env, ref: str) -> uuid.UUID:
    async with env.app.state.session_factory() as s:
        return (await s.execute(text("SELECT id FROM payments WHERE reference=:r"), {"r": ref})).scalar_one()


async def wallet_kobo(env, tokens) -> int:
    return (await env.client.get("/api/v1/wallet", headers=bearer(tokens))).json()["data"]["balance_kobo"]


async def net_credit(env, code: SystemAccount) -> int:
    async with env.app.state.session_factory() as s:
        return await ledger.account_net_credit(s, await ledger.system_account_id(s, code))


async def test_quote_shows_fee_and_total_and_enforces_limits(env) -> None:
    t = await signup(env)
    q = (await env.client.get(f"{F}/quote?amount_kobo={AMOUNT}", headers=bearer(t))).json()["data"]
    assert (q["fee_kobo"], q["total_kobo"], q["fee"], q["total"]) == (FEE, TOTAL, "175.00", "5175.00")
    assert q["min_kobo"] == 50_000 and q["max_kobo"] == 200_000_000
    for bad in (49_999, 200_000_001):
        r = await env.client.get(f"{F}/quote?amount_kobo={bad}", headers=bearer(t))
        assert r.status_code == 422 and r.json()["error"]["code"] == "amount_out_of_range"
    assert (await env.client.get(f"{F}/quote?amount_kobo=50000", headers=bearer(t))).status_code == 200
    assert (await env.client.get(f"{F}/quote?amount_kobo=200000000", headers=bearer(t))).status_code == 200


async def test_initiate_validation_and_auth(env) -> None:
    t = await signup(env)
    assert (await env.client.post(F, json={"amount_kobo": AMOUNT}, headers={"Idempotency-Key": "abcdefgh1"})).status_code == 401
    assert (await env.client.post(F, json={"amount_kobo": AMOUNT}, headers=bearer(t))).status_code == 422  # no key
    for body in ({"amount_kobo": 5000.5}, {"amount_kobo": "500000"}, {"amount_kobo": AMOUNT, "user_id": "x"}, {"amount_kobo": -5}):
        r = await env.client.post(F, json=body, headers={**bearer(t), "Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code == 422, body
    assert (await start(env, t, 49_999)).status_code == 422


async def test_initiate_creates_pending_payment_with_checkout_url_and_exact_total(env) -> None:
    t = await signup(env)
    r = await start(env, t)
    d = r.json()["data"]
    assert r.status_code == 201 and d["status"] == "PENDING" and d["authorization_url"].startswith("https://")
    assert (d["amount_kobo"], d["fee_kobo"], d["total_kobo"]) == (AMOUNT, FEE, TOTAL)
    assert await wallet_kobo(env, t) == 0  # nothing credited by merely starting


async def test_idempotent_initiate_returns_same_session_and_calls_processor_once(env) -> None:
    t = await signup(env)
    a = (await start(env, t, key="idem-key-001")).json()["data"]
    b = (await start(env, t, key="idem-key-001")).json()["data"]
    assert a["reference"] == b["reference"] and env.app.state.payment_processor.initialize_calls == 1
    conflict = await start(env, t, 600_000, key="idem-key-001")
    assert conflict.status_code == 409
    async with env.app.state.session_factory() as s:
        assert (await s.execute(text("SELECT count(*) FROM payments"))).scalar_one() == 1


async def test_concurrent_identical_initiations_create_one_payment(env) -> None:
    t = await signup(env)
    rs = await asyncio.gather(*[start(env, t, key="idem-race-001") for _ in range(5)])
    assert len({r.json()["data"]["reference"] for r in rs if r.status_code == 201}) == 1
    assert env.app.state.payment_processor.initialize_calls == 1  # one checkout session, not five
    async with env.app.state.session_factory() as s:
        assert (await s.execute(text("SELECT count(*) FROM payments"))).scalar_one() == 1


async def test_initialize_timeout_leaves_initiated_then_retry_succeeds(env) -> None:
    t = await signup(env)
    proc = env.app.state.payment_processor
    proc.fail_initialize = True
    r = await start(env, t, key="idem-timeout-1")
    assert r.status_code == 502 and r.json()["error"]["code"] == "payment_provider_unavailable"
    async with env.app.state.session_factory() as s:
        row = (await s.execute(text("SELECT status, attempts FROM payments"))).one()
    assert (row.status, row.attempts) == ("INITIATED", 1)
    proc.fail_initialize = False
    r2 = await start(env, t, key="idem-timeout-1")
    assert r2.status_code == 201 and r2.json()["data"]["status"] == "PENDING"
    assert (await pay_ref(env, r2.json()["data"]["reference"])).endswith("-2")


async def test_verified_webhook_credits_wallet_once_and_books_fee(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref)

    r = await send_webhook(env, pref)
    assert r.status_code == 200 and len(env.app.state.dispatcher.events) == 1
    assert await wallet_kobo(env, t) == 0              # accepted and queued, but NOT yet credited

    (eid,) = await event_ids(env)
    await process(env, eid)
    assert await wallet_kobo(env, t) == AMOUNT          # wallet gets the amount, not the fee
    st = (await env.client.get(f"{F}/{ref}", headers=bearer(t))).json()["data"]
    assert st["status"] == "SUCCESSFUL" and st["paid_at"]
    assert await net_credit(env, SystemAccount.FEES) == FEE
    assert await net_credit(env, SystemAccount.PROCESSOR_CLEARING) == -TOTAL
    async with env.app.state.session_factory() as s:
        assert await ledger.trial_balance_diff(s) == 0
    assert "payment.credited" in await audit_actions(env)


async def test_forged_or_missing_signature_is_rejected_and_stores_nothing(env) -> None:
    t = await signup(env)
    pref = await pay_ref(env, (await start(env, t)).json()["data"]["reference"])
    env.app.state.payment_processor.simulate(pref)
    for sig in ("", "deadbeef", sign(b"other body"), sign(b"x", secret="wrong-secret")):
        assert (await send_webhook(env, pref, signature=sig)).status_code == 401
    assert await event_ids(env) == [] and await wallet_kobo(env, t) == 0


async def test_signed_webhook_claiming_success_does_not_credit_if_processor_disagrees(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)          # processor still says PENDING: customer never paid
    assert (await send_webhook(env, pref)).status_code == 200
    (eid,) = await event_ids(env)
    await process(env, eid)
    assert await wallet_kobo(env, t) == 0
    assert (await env.client.get(f"{F}/{ref}", headers=bearer(t))).json()["data"]["status"] == "PENDING"


async def test_amount_mismatch_is_held_for_review_not_credited(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref, amount_kobo=TOTAL - 1)
    await send_webhook(env, pref)
    await process(env, (await event_ids(env))[0])
    assert await wallet_kobo(env, t) == 0
    st = (await env.client.get(f"{F}/{ref}", headers=bearer(t))).json()["data"]
    assert st["status"] == "MISMATCH" and "reviewing" in st["message"]
    assert "payment.mismatch" in await audit_actions(env)


async def test_currency_mismatch_is_held_for_review(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref, currency="USD")
    await send_webhook(env, pref)
    await process(env, (await event_ids(env))[0])
    assert await wallet_kobo(env, t) == 0
    assert (await env.client.get(f"{F}/{ref}", headers=bearer(t))).json()["data"]["status"] == "MISMATCH"


async def test_duplicate_webhooks_store_one_event_and_credit_once(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref)
    rs = await asyncio.gather(*[send_webhook(env, pref) for _ in range(6)])
    assert all(r.status_code == 200 for r in rs)
    ids = await event_ids(env)
    assert len(ids) == 1
    await asyncio.gather(*[process(env, ids[0]) for _ in range(5)])
    assert await wallet_kobo(env, t) == AMOUNT
    again = await send_webhook(env, pref)             # replay after completion
    assert again.json()["message"] == "duplicate" and await wallet_kobo(env, t) == AMOUNT


async def test_webhook_processing_and_polling_race_credits_once(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref)
    await send_webhook(env, pref)
    (eid,) = await event_ids(env)

    async def poll():
        return await env.client.get(f"{F}/{ref}", headers=bearer(t))

    await asyncio.gather(process(env, eid), poll(), poll(), process(env, eid))
    assert await wallet_kobo(env, t) == AMOUNT
    async with env.app.state.session_factory() as s:
        assert (await s.execute(text("SELECT count(*) FROM ledger_journals WHERE kind='wallet.funding'"))).scalar_one() == 1
        assert (await WalletService(s).verify_integrity(uuid.UUID((await env.client.get("/api/v1/users/me", headers=bearer(t))).json()["data"]["id"]))).ok


async def test_lost_webhook_is_recovered_by_polling(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    env.app.state.payment_processor.simulate(await pay_ref(env, ref))
    st = (await env.client.get(f"{F}/{ref}", headers=bearer(t))).json()["data"]
    assert st["status"] == "SUCCESSFUL" and await wallet_kobo(env, t) == AMOUNT


async def test_processor_outage_during_processing_keeps_event_for_retry(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    proc = env.app.state.payment_processor
    proc.simulate(pref)
    await send_webhook(env, pref)
    (eid,) = await event_ids(env)
    proc.fail_verify = True
    try:
        await process(env, eid)
        raise AssertionError("expected ProcessorUnavailableError")
    except ProcessorUnavailableError:
        pass
    assert await wallet_kobo(env, t) == 0
    async with env.app.state.session_factory() as s:
        row = (await s.execute(text("SELECT status, attempts FROM webhook_events"))).one()
        assert (row.status, row.attempts) == ("FAILED", 1)
        assert (await s.execute(text("SELECT status FROM payments"))).scalar_one() == "PENDING"  # unknown != failed
    proc.fail_verify = False
    await process(env, eid)
    assert await wallet_kobo(env, t) == AMOUNT


async def test_failed_payment_can_still_succeed_on_retry_of_same_session(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref, proc = await pay_ref(env, ref), env.app.state.payment_processor
    pid = await payment_id(env, ref)
    proc.simulate(pref, status=VerifyStatus.FAILED)
    async with env.app.state.session_factory() as s:
        assert (await service(env, s).settle(pid, source="test")).status == "FAILED"
    assert await wallet_kobo(env, t) == 0
    proc.simulate(pref, status=VerifyStatus.SUCCESS)
    async with env.app.state.session_factory() as s:
        assert (await service(env, s).settle(pid, source="test")).status == "SUCCESSFUL"
    assert await wallet_kobo(env, t) == AMOUNT


async def test_unknown_reference_webhook_is_ignored_and_audited(env) -> None:
    assert (await send_webhook(env, "fnd_unknown-1", txn_id=777)).status_code == 200
    await process(env, (await event_ids(env))[0])
    async with env.app.state.session_factory() as s:
        assert (await s.execute(text("SELECT status FROM webhook_events"))).scalar_one() == "IGNORED"
    assert "payment.webhook_unknown_reference" in await audit_actions(env)


async def test_other_event_types_are_ignored(env) -> None:
    t = await signup(env)
    pref = await pay_ref(env, (await start(env, t)).json()["data"]["reference"])
    await send_webhook(env, pref, event="transfer.success", txn_id=5)
    await process(env, (await event_ids(env))[0])
    assert await wallet_kobo(env, t) == 0


async def test_users_cannot_see_each_others_payments(env) -> None:
    ta, tb = await signup(env), await signup(env, phone="08087654321")
    ref = (await start(env, ta)).json()["data"]["reference"]
    assert (await env.client.get(f"{F}/{ref}", headers=bearer(tb))).status_code == 404
    assert (await env.client.get(f"{F}/not-a-reference", headers=bearer(ta))).status_code == 422
    assert (await env.client.get(F, headers=bearer(tb))).json()["data"]["items"] == []
    assert len((await env.client.get(F, headers=bearer(ta))).json()["data"]["items"]) == 1


async def test_sweeper_recovers_stored_event_when_queue_message_was_lost(env) -> None:
    t = await signup(env)
    ref = (await start(env, t)).json()["data"]["reference"]
    pref = await pay_ref(env, ref)
    env.app.state.payment_processor.simulate(pref)
    await send_webhook(env, pref)
    async with env.app.state.session_factory() as s:
        await s.execute(text("UPDATE webhook_events SET received_at = now() - interval '5 minutes'"))
        await s.execute(text("UPDATE payments SET created_at = now() - interval '5 minutes'"))
        await s.commit()
    async with env.app.state.session_factory() as s:
        assert await service(env, s).sweep() >= 1
    assert await wallet_kobo(env, t) == AMOUNT
