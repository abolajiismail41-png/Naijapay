import asyncio
import json
import uuid
from datetime import timedelta

from sqlalchemy import text

from app.core.money import Money
from app.modules.ledger import interface as ledger
from app.modules.ledger.interface import SystemAccount
from app.modules.providers.base import Outcome
from app.modules.transactions.execution import TransactionService
from app.modules.wallet.service import WalletService
from tests.api.helpers import PHONE, audit_actions, bearer, set_role, signup

NGN = Money.from_naira
A = "/api/v1/airtime"
FACE = 20_000                 # NGN 200 airtime
COST = 19_500                 # sandbox: 2.5% provider discount
PRICE = 19_890                # cost + 2.00% markup = 195 + 3.90 = NGN 198.90 (under face value 200)
PIN = "4821"


def prov(env):
    return env.app.state.bill_providers["inlomax"]


def svc(env, s) -> TransactionService:
    return TransactionService(s, env.redis, env.app.state.settings, env.app.state.bill_providers)


async def uid(env, t) -> uuid.UUID:
    return uuid.UUID((await env.client.get("/api/v1/users/me", headers=bearer(t))).json()["data"]["id"])


async def fund(env, user_id, amount: Money, ref: str) -> None:
    async with env.app.state.session_factory() as s:
        await WalletService(s).credit(user_id, amount, reference=ref, kind="test.funding",
                                      source=SystemAccount.PROCESSOR_CLEARING)
        await s.commit()


async def customer(env, wallet=NGN(1000), phone=PHONE):
    t = await signup(env, phone=phone)
    u = await uid(env, t)
    await env.client.post("/api/v1/auth/pin/set", headers=bearer(t), json={"password": "Str0ng-pass!", "pin": PIN})
    if wallet.kobo:
        await fund(env, u, wallet, f"fund:{u}")
    return t, u


async def token(env, t) -> str:
    return (await env.client.post("/api/v1/auth/pin/verify", headers=bearer(t), json={"pin": PIN})).json()["data"]["pin_token"]


async def buy(env, t, *, amount=FACE, price=PRICE, key=None, tok=None, network="MTN", phone="08031234567"):
    return await env.client.post(A, json={"network": network, "phone": phone, "amount_kobo": amount,
                                          "confirmed_price_kobo": price},
                                 headers={**bearer(t), "X-PIN-Token": tok or await token(env, t),
                                          "Idempotency-Key": key or uuid.uuid4().hex})


async def tid(env, ref: str) -> uuid.UUID:
    async with env.app.state.session_factory() as s:
        return (await s.execute(text("SELECT id FROM transactions WHERE reference=:r"), {"r": ref})).scalar_one()


async def run(env, ref: str):
    async with env.app.state.session_factory() as s:
        return await svc(env, s).execute(await tid(env, ref))


async def sql(env, q: str, **p):
    async with env.app.state.session_factory() as s:
        r = await s.execute(text(q), p)
        await s.commit()
        return r.all() if r.returns_rows else None


async def balance(env, t) -> int:
    return (await env.client.get("/api/v1/wallet", headers=bearer(t))).json()["data"]["balance_kobo"]


async def status(env, t, ref) -> dict:
    return (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).json()["data"]


async def net(env, code: SystemAccount) -> int:
    async with env.app.state.session_factory() as s:
        return await ledger.account_net_credit(s, await ledger.system_account_id(s, code))


async def all_checks_ok(env) -> bool:
    from app.modules.admin import profit
    async with env.app.state.session_factory() as s:
        checks = await profit.ledger_checks(s)
    assert all(c["ok"] for c in checks), checks
    return True


# ---------------- quoting & validation ----------------
async def test_quote_shows_only_the_customer_price(env) -> None:
    t, _ = await customer(env, NGN(0))
    r = await env.client.post(f"{A}/quote", headers=bearer(t), json={"network": "MTN", "amount_kobo": FACE})
    d = r.json()["data"]
    assert d["price_kobo"] == PRICE and d["price"] == "198.90"
    assert set(d) == {"network", "amount_kobo", "amount", "price_kobo", "price"}


async def test_validation(env) -> None:
    t, _ = await customer(env, NGN(0))
    for body in ({"network": "VODAFONE", "amount_kobo": FACE}, {"network": "MTN", "amount_kobo": 5050},
                 {"network": "MTN", "amount_kobo": 4900}, {"network": "MTN", "amount_kobo": 5_000_100},
                 {"network": "MTN", "amount_kobo": 20000.0}, {"network": "MTN", "amount_kobo": FACE, "x": 1}):
        assert (await env.client.post(f"{A}/quote", headers=bearer(t), json=body)).status_code == 422, body


# ---------------- happy path & accounting ----------------
async def test_purchase_success_flow_and_ledger_separation(env) -> None:
    t, u = await customer(env)
    r = await buy(env, t)
    d = r.json()["data"]
    assert r.status_code == 202 and d["status"] == "PENDING" and d["display_status"] == "PROCESSING"
    ref = d["reference"]
    assert await balance(env, t) == 100_000 - PRICE            # held immediately
    assert await net(env, SystemAccount.REVENUE) == 0 and await net(env, SystemAccount.PROVIDER_COST) == 0  # not income yet
    assert await net(env, SystemAccount.PROVIDER_CLEARING) == PRICE and await all_checks_ok(env)
    assert len(env.app.state.dispatcher.executes) == 1

    await run(env, ref)
    st = await status(env, t, ref)
    assert st["status"] == "SUCCESSFUL" and st["display_status"] == "SUCCESSFUL"
    call = prov(env).calls[0]
    assert (call.request_id, call.phone, call.service_id, call.amount) == (ref, "08031234567", "1", Money(FACE))
    assert await net(env, SystemAccount.PROVIDER_CLEARING) == 0
    assert await net(env, SystemAccount.REVENUE) == PRICE      # recognised only now: price + discount - fee
    assert -await net(env, SystemAccount.PROVIDER_COST) == COST and await net(env, SystemAccount.PROVIDER_FLOAT) == COST
    assert await all_checks_ok(env)
    snap = (await sql(env, "SELECT cost_kobo, markup_kobo, customer_price_kobo, gross_profit_kobo, margin_pct FROM pricing_snapshots"))[0]
    assert (snap[0], snap[1], snap[2], snap[3]) == (COST, 390, PRICE, 390) and float(snap[4]) == 1.96
    assert (await sql(env, "SELECT provider_cost_kobo FROM transactions"))[0][0] == COST


async def test_customer_responses_never_contain_cost_or_profit(env) -> None:
    t, _ = await customer(env)
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    bodies = [(await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).text,
              (await env.client.get("/api/v1/transactions", headers=bearer(t))).text,
              (await env.client.get(f"{A}/networks", headers=bearer(t))).text,
              (await env.client.get("/api/v1/wallet/entries", headers=bearer(t))).text]
    blob = json.dumps(bodies).lower()
    for word in ("cost", "markup", "margin", "profit", "provider", "discount_bps", "inlomax", "snapshot"):
        assert word not in blob, word
    assert str(COST) not in blob and "19500" not in blob


# ---------------- price protection ----------------
async def test_price_change_requires_reconfirmation_and_replay_ignores_it(env) -> None:
    t, _ = await customer(env)
    key = "idem-price-0001"
    r = await buy(env, t, price=PRICE - 1, key=key)
    assert r.status_code == 409 and r.json()["error"]["code"] == "price_changed" and "198.90" in r.json()["error"]["message"]
    assert await balance(env, t) == 100_000
    ok1 = await buy(env, t, key=key)
    assert ok1.status_code == 202
    await sql(env, "UPDATE pricing_rules SET markup_bps = 500 WHERE active")   # price moved after the order was placed
    again = await buy(env, t, key=key, price=PRICE)
    assert again.status_code == 202 and again.json()["data"]["reference"] == ok1.json()["data"]["reference"]


async def test_below_cost_is_blocked_with_neutral_message_and_audited(env) -> None:
    t, _ = await customer(env)
    await sql(env, "UPDATE pricing_rules SET markup_bps = -1000 WHERE active")
    r = await buy(env, t, price=17_550)
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable"
    assert "cost" not in r.text.lower() and "17550" not in r.text
    assert await balance(env, t) == 100_000 and "pricing.blocked" in await audit_actions(env)
    q = await env.client.post(f"{A}/quote", headers=bearer(t), json={"network": "MTN", "amount_kobo": FACE})
    assert q.status_code == 503


async def test_snapshot_survives_later_price_changes_and_is_immutable(env) -> None:
    t, _ = await customer(env)
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    await sql(env, "UPDATE pricing_rules SET active=false")
    await sql(env, "UPDATE provider_prices SET value = 100")
    snap = (await sql(env, "SELECT customer_price_kobo, cost_kobo FROM pricing_snapshots"))[0]
    assert tuple(snap) == (PRICE, COST)
    for stmt in ("UPDATE pricing_snapshots SET cost_kobo = 1", "DELETE FROM pricing_snapshots"):
        try:
            await sql(env, stmt)
            raise AssertionError("snapshot mutation should be blocked")
        except Exception as exc:  # noqa: BLE001
            assert "append-only" in str(exc)


async def test_stale_synced_provider_cost_blocks_new_sales(env) -> None:
    t, _ = await customer(env)
    await sql(env, "UPDATE provider_prices SET source='SYNCED', synced_at = now() - interval '5 days'")
    assert (await buy(env, t)).status_code == 503


# ---------------- PIN, idempotency, concurrency ----------------
async def test_pin_step_up_required_and_single_use(env) -> None:
    t, _ = await customer(env)
    base = {"network": "MTN", "phone": "08031234567", "amount_kobo": FACE, "confirmed_price_kobo": PRICE}
    assert (await env.client.post(A, json=base, headers={**bearer(t), "Idempotency-Key": "k-no-token-1"})).status_code == 403
    assert (await env.client.post(A, json=base, headers={**bearer(t), "X-PIN-Token": "junk", "Idempotency-Key": "k-junk-0001"})).status_code == 401
    tok = await token(env, t)
    assert (await buy(env, t, tok=tok, key="k-first-0001")).status_code == 202
    again = await buy(env, t, tok=tok, key="k-second-001")
    assert again.status_code == 403 and await balance(env, t) == 100_000 - PRICE
    assert (await buy(env, t, tok=tok, key="k-first-0001")).status_code == 202   # replay still fine


async def test_pin_token_is_bound_to_its_user(env) -> None:
    ta, _ = await customer(env)
    tb, _ = await customer(env, phone="08087654321")
    r = await buy(env, ta, tok=await token(env, tb))
    assert r.status_code == 403


async def test_insufficient_funds_leaves_no_trace_and_does_not_burn_the_pin_token(env) -> None:
    t, u = await customer(env, NGN(100))
    tok = await token(env, t)
    r = await buy(env, t, tok=tok)
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    assert (await sql(env, "SELECT count(*) FROM transactions"))[0][0] == 0
    await fund(env, u, NGN(500), "fund:more")
    assert (await buy(env, t, tok=tok)).status_code == 202


async def test_idempotency_same_key_one_charge_conflicting_payload_rejected(env) -> None:
    t, _ = await customer(env)
    a = await buy(env, t, key="idem-airtime-01")
    b = await buy(env, t, key="idem-airtime-01")
    assert a.json()["data"]["reference"] == b.json()["data"]["reference"]
    assert await balance(env, t) == 100_000 - PRICE
    c = await buy(env, t, key="idem-airtime-01", amount=30_000, price=29_835)
    assert c.status_code == 409


async def test_concurrent_identical_requests_charge_once(env) -> None:
    t, _ = await customer(env)
    toks = [await token(env, t) for _ in range(5)]
    rs = await asyncio.gather(*[buy(env, t, key="idem-race-airtime", tok=k) for k in toks])
    assert {r.json()["data"]["reference"] for r in rs if r.status_code == 202} and all(r.status_code == 202 for r in rs)
    assert len({r.json()["data"]["reference"] for r in rs}) == 1
    assert await balance(env, t) == 100_000 - PRICE and (await sql(env, "SELECT count(*) FROM transactions"))[0][0] == 1


async def test_double_spend_of_the_same_balance_only_one_wins(env) -> None:
    t, _ = await customer(env, Money(PRICE))
    toks = [await token(env, t) for _ in range(2)]
    rs = await asyncio.gather(*[buy(env, t, tok=k) for k in toks])
    assert sorted(r.status_code for r in rs) == [202, 422] and await balance(env, t) == 0
    assert await all_checks_ok(env)


async def test_concurrent_execute_calls_provider_once(env) -> None:
    t, _ = await customer(env)
    ref = (await buy(env, t)).json()["data"]["reference"]
    await asyncio.gather(*[run(env, ref) for _ in range(5)])
    assert len(prov(env).calls) == 1 and (await status(env, t, ref))["status"] == "SUCCESSFUL"


# ---------------- failures, unknowns, refunds ----------------
async def test_definite_failure_refunds_once_and_leaves_revenue_untouched(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("failed")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    await run(env, ref)
    st = await status(env, t, ref)
    assert st["status"] == "REFUNDED" and "returned to your wallet" in st["message"]
    assert await balance(env, t) == 100_000 and len(prov(env).calls) == 1
    assert await net(env, SystemAccount.REVENUE) == 0 and await net(env, SystemAccount.PROVIDER_CLEARING) == 0
    events = [r[0] for r in await sql(env, "SELECT to_status FROM transaction_events ORDER BY id")]
    assert events == ["PENDING", "PROCESSING", "FAILED", "REFUNDED"] and await all_checks_ok(env)


async def test_timeout_is_unknown_never_auto_refunded_then_escalated(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("timeout")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    st = await status(env, t, ref)
    assert st["status"] == "UNKNOWN" and st["display_status"] == "PENDING" and "do not retry" in st["message"].lower()
    assert await balance(env, t) == 100_000 - PRICE and await all_checks_ok(env)
    await sql(env, "UPDATE transactions SET sent_at = now() - interval '20 minutes'")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert "transaction.unknown_unresolvable" in await audit_actions(env)
    assert (await status(env, t, ref))["status"] == "UNKNOWN" and await balance(env, t) == 100_000 - PRICE


async def test_manual_resolution_requires_finance_permission_and_is_final(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("timeout", "timeout")
    r1 = (await buy(env, t)).json()["data"]["reference"]
    r2 = (await buy(env, t, key="idem-second-000")).json()["data"]["reference"]
    await run(env, r1)
    await run(env, r2)
    url = lambda ref: f"/api/v1/admin/transactions/{ref}/resolve"  # noqa: E731
    body = {"outcome": "FAILED", "note": "confirmed not delivered on provider dashboard"}
    assert (await env.client.post(url(r1), headers=bearer(t), json=body)).status_code == 403
    await set_role(env, "+2348031234567", "SUPPORT")
    assert (await env.client.post(url(r1), headers=bearer(t), json=body)).status_code == 403
    await set_role(env, "+2348031234567", "FINANCE")
    assert (await env.client.post(url(r1), headers=bearer(t), json=body)).status_code == 200
    assert (await status(env, t, r1))["status"] == "REFUNDED"
    assert (await env.client.post(url(r1), headers=bearer(t), json=body)).status_code == 409
    ok = await env.client.post(url(r2), headers=bearer(t), json={"outcome": "SUCCESS", "provider_cost_kobo": 19_400,
                                                                  "note": "delivered per provider records"})
    assert ok.status_code == 200 and (await status(env, t, r2))["status"] == "SUCCESSFUL"
    assert (await sql(env, "SELECT provider_cost_kobo FROM transactions WHERE reference=:r", r=r2))[0][0] == 19_400
    assert "transaction.manual_resolution" in await audit_actions(env) and await all_checks_ok(env)


async def test_processing_then_verification_completes(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("processing")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    assert (await status(env, t, ref))["status"] == "PROCESSING"
    prov(env).set_status("sbx_1", Outcome.SUCCESS)
    async with env.app.state.session_factory() as s:
        await svc(env, s).verify(await tid(env, ref))
    assert (await status(env, t, ref))["status"] == "SUCCESSFUL" and await all_checks_ok(env)


async def test_unknown_with_reference_is_resolved_by_sweeper_after_backoff(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("processing")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    prov(env).fail_status = True
    async with env.app.state.session_factory() as s:
        await svc(env, s).verify(await tid(env, ref))
    assert (await status(env, t, ref))["status"] == "UNKNOWN"
    prov(env).fail_status = False
    prov(env).set_status("sbx_1", Outcome.SUCCESS)
    await sql(env, "UPDATE transactions SET next_check_at = now() - interval '1 minute'")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert (await status(env, t, ref))["status"] == "SUCCESSFUL"


async def test_lost_in_flight_call_becomes_unknown_not_refunded(env) -> None:
    t, _ = await customer(env)
    ref = (await buy(env, t)).json()["data"]["reference"]
    await sql(env, "UPDATE transactions SET status='PROCESSING', sent_at = now() - interval '5 minutes'")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert (await status(env, t, ref))["status"] == "UNKNOWN" and await balance(env, t) == 100_000 - PRICE


async def test_open_circuit_keeps_purchase_unsent_then_refunds_after_grace(env) -> None:
    t, _ = await customer(env)
    await env.redis.set("cb:provider:inlomax:open", 1, ex=600)
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    assert (await status(env, t, ref))["status"] == "PENDING" and prov(env).calls == []
    await sql(env, "UPDATE transactions SET created_at = now() - interval '11 minutes', updated_at = now() - interval '11 minutes'")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert (await status(env, t, ref))["status"] == "REFUNDED" and await balance(env, t) == 100_000


async def test_circuit_opens_after_repeated_unknowns(env) -> None:
    t, _ = await customer(env, NGN(5000))
    prov(env).queue(*["timeout"] * 5)
    for i in range(5):
        await run(env, (await buy(env, t, key=f"idem-cb-{i:04d}x")).json()["data"]["reference"])
    assert await env.redis.exists("cb:provider:inlomax:open")
    ref = (await buy(env, t, key="idem-cb-after-x")).json()["data"]["reference"]
    await run(env, ref)
    assert len(prov(env).calls) == 5 and (await status(env, t, ref))["status"] == "PENDING"


async def test_late_success_after_refund_is_flagged_not_applied(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("failed")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    await sql(env, "UPDATE transactions SET provider_reference='sbx_late'")
    prov(env).set_status("sbx_late", Outcome.SUCCESS)
    async with env.app.state.session_factory() as s:
        await svc(env, s).verify(await tid(env, ref))
    assert (await status(env, t, ref))["status"] == "REFUNDED"
    assert "transaction.late_success_after_refund" in await audit_actions(env)


# ---------------- provider webhook ----------------
HOOK = "/api/v1/webhooks/inlomax/test-inlomax-hook-token-1234567890"


def hook(ref: str, status: str) -> bytes:
    return json.dumps({"status": status, "message": "x", "data": {"reference": ref, "status": status, "amount": 200}}).encode()


async def test_webhook_requires_secret_token_and_never_trusts_the_body(env) -> None:
    t, _ = await customer(env)
    prov(env).queue("processing")
    ref = (await buy(env, t)).json()["data"]["reference"]
    await run(env, ref)
    assert (await env.client.post("/api/v1/webhooks/inlomax/wrong-token", content=hook("sbx_1", "success"))).status_code == 404
    assert (await sql(env, "SELECT count(*) FROM webhook_events"))[0][0] == 0
    assert (await env.client.post(HOOK, content=b"{bad")).status_code == 400

    # body claims FAILED, the provider API says SUCCESS: the API wins
    prov(env).set_status("sbx_1", Outcome.SUCCESS)
    r = await env.client.post(HOOK, content=hook("sbx_1", "failed"))
    assert r.status_code == 200 and len(env.app.state.dispatcher.provider_events) == 1
    eid = (await sql(env, "SELECT id FROM webhook_events"))[0][0]
    async with env.app.state.session_factory() as s:
        await svc(env, s).process_provider_webhook(eid)
    assert (await status(env, t, ref))["status"] == "SUCCESSFUL" and await balance(env, t) == 100_000 - PRICE


async def test_webhook_duplicates_and_unmatched_references(env) -> None:
    t, _ = await customer(env)
    await asyncio.gather(*[env.client.post(HOOK, content=hook("sbx_nope", "success")) for _ in range(4)])
    assert (await sql(env, "SELECT count(*) FROM webhook_events"))[0][0] == 1
    eid = (await sql(env, "SELECT id FROM webhook_events"))[0][0]
    async with env.app.state.session_factory() as s:
        await svc(env, s).process_provider_webhook(eid)
    row = (await sql(env, "SELECT status, attempts FROM webhook_events"))[0]
    assert tuple(row) == ("FAILED", 1)   # kept for the sweeper: the transaction may simply not be linked yet


# ---------------- isolation ----------------
async def test_users_cannot_see_others_transactions_and_listing_paginates(env) -> None:
    ta, _ = await customer(env)
    tb, _ = await customer(env, phone="08087654321")
    refs = [(await buy(env, ta, key=f"idem-list-{i:04d}x")).json()["data"]["reference"] for i in range(3)]
    assert (await env.client.get(f"/api/v1/transactions/{refs[0]}", headers=bearer(tb))).status_code == 404
    assert (await env.client.get("/api/v1/transactions", headers=bearer(tb))).json()["data"]["items"] == []
    page = (await env.client.get("/api/v1/transactions?limit=2", headers=bearer(ta))).json()["data"]
    assert [i["reference"] for i in page["items"]] == refs[::-1][:2] and page["next_cursor"]
    rest = (await env.client.get(f"/api/v1/transactions?limit=2&cursor={page['next_cursor']}", headers=bearer(ta))).json()["data"]
    assert [i["reference"] for i in rest["items"]] == [refs[0]] and rest["next_cursor"] is None
