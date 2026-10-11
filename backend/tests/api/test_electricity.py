import asyncio  # noqa: F401
import uuid
from types import SimpleNamespace

import pytest

from app.core.money import Money
from app.modules.electricity.sync import sync_electricity
from app.modules.ledger.interface import SystemAccount
from tests.api.helpers import audit_actions, bearer, signup
from tests.api.test_admin_pricing_profit import F, P as PRICING, admin
from tests.api.test_airtime import (  # noqa: F401
    all_checks_ok, balance, customer, fund, net, prov, run, sql, status, svc, token, tid,
)

NGN = Money.from_naira
E = "/api/v1/electricity"
ADM = "/api/v1/admin/electricity"
AMT, PRICE_E, COST_E = 500_000, 505_000, 497_500   # NGN 5,000 token value; +NGN 50 fee; provider cost at 0.5% discount
METER = "12345678901"


async def seed_discos(env, list_all: bool = True):
    async with env.app.state.session_factory() as s:
        rep = await sync_electricity(s, prov(env))
    if list_all:
        await sql(env, "UPDATE electricity_discos SET listed = true")
    return rep


async def disco(env, code="IKEJA") -> str:
    return str((await sql(env, "SELECT id FROM electricity_discos WHERE code=:c", c=code))[0][0])


async def validate(env, t, code="IKEJA", mtype="PREPAID", meter=METER):
    return await env.client.post(f"{E}/validate", headers=bearer(t),
                                 json={"disco_id": await disco(env, code), "meter_type": mtype, "meter_number": meter})


async def vid(env, t, **kw) -> str:
    return (await validate(env, t, **kw)).json()["data"]["validation_id"]


async def pay(env, t, validation_id, *, amount=AMT, price=PRICE_E, key=None, tok=None):
    return await env.client.post(E, json={"validation_id": validation_id, "amount_kobo": amount, "confirmed_price_kobo": price},
                                 headers={**bearer(t), "X-PIN-Token": tok or await token(env, t),
                                          "Idempotency-Key": key or uuid.uuid4().hex})


async def get_token(env, t, ref):
    return await env.client.get(f"{E}/{ref}/token", headers=bearer(t))


async def test_sync_discovers_unlisted_discos_with_costs_and_admin_sees_sample_margin(env) -> None:
    t, _ = await customer(env, NGN(0))
    fin = await admin(env, "FINANCE", "08044440000")
    rep = await seed_discos(env, list_all=False)
    assert (rep.discos_created, rep.prices_created) == (2, 3)
    assert (await env.client.get(f"{E}/discos", headers=bearer(t))).json()["data"] == []
    rows = await sql(env, "SELECT value FROM provider_prices WHERE category='ELECTRICITY' ORDER BY value")
    assert [r[0] for r in rows] == [50, 50, 120]
    listing = (await env.client.get(f"{ADM}/discos", headers=bearer(fin))).json()["data"]
    ik = next(x for x in listing if x["code"] == "IKEJA")["types"]["PREPAID"]
    assert (ik["sample_customer_price"], ik["sample_gross_profit"], ik["sample_margin_pct"]) == ("5050.00", "75.00", "1.49")
    assert (await env.client.get(f"{ADM}/discos", headers=bearer(t))).status_code == 403
    again = await seed_discos(env, list_all=False)
    assert (again.discos_created, again.prices_created) == (0, 0)


async def test_admin_can_create_edit_and_list_discos_by_hand_but_not_unsellable_ones(env) -> None:
    t, _ = await customer(env, NGN(0))
    fin = await admin(env, "FINANCE", "08044440000")
    body = {"code": "EKO", "name": "Eko Electricity (EKEDC)", "provider_disco_code": "eko", "prepaid_service_id": "ek-pre",
            "prepaid_discount_bps": 100}
    created = await env.client.post(f"{ADM}/discos", headers=bearer(fin), json=body)
    assert created.status_code == 201 and (await env.client.post(f"{ADM}/discos", headers=bearer(fin), json=body)).status_code == 409
    assert (await env.client.post(f"{ADM}/discos", headers=bearer(t), json=body)).status_code == 403
    did = created.json()["data"]["id"]
    assert (await env.client.patch(f"{ADM}/discos/{did}", headers=bearer(fin), json={"listed": True})).status_code == 200
    items = (await env.client.get(f"{E}/discos", headers=bearer(t))).json()["data"]
    assert [(i["code"], i["meter_types"]) for i in items] == [("EKO", ["PREPAID"])]
    nocost = (await env.client.post(f"{ADM}/discos", headers=bearer(fin), json={"code": "KANO", "name": "Kano Electric", "provider_disco_code": "kano"})).json()["data"]["id"]
    r = await env.client.patch(f"{ADM}/discos/{nocost}", headers=bearer(fin), json={"listed": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "disco_not_sellable"
    assert "electricity_disco.created" in await audit_actions(env) and "provider_price.changed" not in await audit_actions(env)


async def test_meter_validation_flow_errors_and_rate_limit(env) -> None:
    t, _ = await customer(env, NGN(0))
    await seed_discos(env)
    ok = await validate(env, t)
    d = ok.json()["data"]
    assert ok.status_code == 200 and d["customer_name"] == "TEST METER" and d["meter_number"] == "*******8901"
    assert len(d["validation_id"]) == 32 and prov(env).validate_calls == [METER]
    bad = await validate(env, t, meter="12345670000")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_meter" and "meter.validation_failed" in await audit_actions(env)
    prov(env).fail_validate = True
    down = await validate(env, t)
    assert down.status_code == 502 and down.json()["error"]["code"] == "provider_unavailable"
    prov(env).fail_validate = False
    for body in ({"meter_number": "12ab"}, {"meter_number": "123"}, {"meter_type": "HYBRID"}, {"extra": 1}):
        r = await env.client.post(f"{E}/validate", headers=bearer(t), json={"disco_id": await disco(env), "meter_type": "PREPAID",
                                                                              "meter_number": METER, **body})
        assert r.status_code == 422, body
    codes = [(await validate(env, t)).status_code for _ in range(9)]
    assert codes[-1] == 429


async def test_validation_is_private_and_expires(env) -> None:
    ta, _ = await customer(env, NGN(0))
    tb, _ = await customer(env, NGN(0), phone="08087654321")
    await seed_discos(env)
    v = await vid(env, ta)
    q = {"validation_id": v, "amount_kobo": AMT}
    assert (await env.client.post(f"{E}/quote", headers=bearer(ta), json=q)).status_code == 200
    other = await env.client.post(f"{E}/quote", headers=bearer(tb), json=q)
    assert other.status_code == 409 and other.json()["error"]["code"] == "meter_validation_expired"
    await env.redis.delete(f"meter:val:{v}")
    assert (await env.client.post(f"{E}/quote", headers=bearer(ta), json=q)).status_code == 409


async def test_quote_shows_fee_and_total_never_cost_and_enforces_amounts(env) -> None:
    t, _ = await customer(env, NGN(0))
    await seed_discos(env)
    v = await vid(env, t)
    d = (await env.client.post(f"{E}/quote", headers=bearer(t), json={"validation_id": v, "amount_kobo": AMT})).json()["data"]
    assert (d["amount_kobo"], d["service_fee_kobo"], d["price_kobo"], d["price"]) == (AMT, 5_000, PRICE_E, "5050.00")
    for amount in (49_900, 10_000_100, 500_050, 0):
        r = await env.client.post(f"{E}/quote", headers=bearer(t), json={"validation_id": v, "amount_kobo": amount})
        assert r.status_code == 422, amount


async def test_prepaid_purchase_encrypts_the_token_and_hands_it_over_only_via_the_token_endpoint(env) -> None:
    ta, _ = await customer(env, NGN(10_000))
    tb, _ = await customer(env, NGN(0), phone="08087654321")
    await seed_discos(env)
    r = await pay(env, ta, await vid(env, ta))
    d = r.json()["data"]
    assert r.status_code == 202 and d["status"] == "PENDING" and d["disco"] == "Ikeja Electric (IKEDC)" and d["meter_number"] == "*******8901"
    ref = d["reference"]
    assert await balance(env, ta) == 1_000_000 - PRICE_E and (await get_token(env, ta, ref)).status_code == 404
    await run(env, ref)
    view = (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(ta))).json()["data"]
    assert view["status"] == "SUCCESSFUL" and view["token_available"] is True
    tok = (await get_token(env, ta, ref)).json()["data"]
    assert len(tok["token"]) == 20 and tok["units"] == "31.2" and tok["meter_number"] == "*******8901"
    assert tok["token"] not in (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(ta))).text
    assert tok["token"] not in (await env.client.get("/api/v1/transactions", headers=bearer(ta))).text
    cipher = (await sql(env, "SELECT token_ciphertext FROM electricity_orders"))[0][0]
    assert cipher.startswith("v1:") and tok["token"] not in cipher
    assert (await get_token(env, tb, ref)).status_code == 404 and "token.viewed" in await audit_actions(env)
    req = prov(env).calls[0]
    assert (req.service_id, req.provider_disco_code, req.meter_number, req.meter_type, req.amount) == ("ik-pre", "ikeja", METER, "PREPAID", Money(AMT))
    snap = (await sql(env, "SELECT cost_kobo, markup_kobo, fee_kobo, customer_price_kobo, gross_profit_kobo FROM pricing_snapshots"))[0]
    assert tuple(snap) == (COST_E, 2_500, 5_000, PRICE_E, 7_500)
    assert await net(env, SystemAccount.REVENUE) == AMT and await net(env, SystemAccount.SERVICE_FEES) == 5_000
    assert -await net(env, SystemAccount.PROVIDER_COST) == COST_E and await all_checks_ok(env)


async def test_postpaid_purchase_has_no_token(env) -> None:
    t, _ = await customer(env, NGN(10_000))
    await seed_discos(env)
    ref = (await pay(env, t, await vid(env, t, mtype="POSTPAID"))).json()["data"]["reference"]
    await run(env, ref)
    view = (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).json()["data"]
    assert view["status"] == "SUCCESSFUL" and view["token_available"] is False and view["meter_type"] == "POSTPAID"
    assert (await sql(env, "SELECT token_status FROM electricity_orders"))[0][0] == "NOT_APPLICABLE"
    assert (await get_token(env, t, ref)).status_code == 404 and prov(env).calls[0].service_id == "ik-post"


async def test_failure_refunds_and_timeout_resolves_manually_with_the_token(env) -> None:
    t, _ = await customer(env, NGN(20_000))
    fin = await admin(env, "FINANCE", "08044440000")
    await seed_discos(env)
    v = await vid(env, t)
    prov(env).queue("failed", "timeout")
    r1 = (await pay(env, t, v)).json()["data"]["reference"]
    r2 = (await pay(env, t, v)).json()["data"]["reference"]
    await run(env, r1)
    await run(env, r2)
    assert (await status(env, t, r1))["status"] == "REFUNDED" and (await status(env, t, r2))["status"] == "UNKNOWN"
    assert await balance(env, t) == 2_000_000 - PRICE_E and await all_checks_ok(env)
    res = await env.client.post(f"/api/v1/admin/transactions/{r2}/resolve", headers=bearer(fin), json={
        "outcome": "SUCCESS", "provider_cost_kobo": 497_000, "token": "11112222333344445555", "note": "confirmed in provider dashboard"})
    assert res.status_code == 200 and (await status(env, t, r2))["status"] == "SUCCESSFUL"
    assert (await get_token(env, t, r2)).json()["data"]["token"] == "11112222333344445555"
    assert await all_checks_ok(env)


async def test_missing_token_is_flagged_recovered_by_the_sweeper_and_eventually_escalated(env) -> None:
    t, _ = await customer(env, NGN(20_000))
    await seed_discos(env)
    prov(env).queue("no_token", "no_token")
    v = await vid(env, t)
    ref = (await pay(env, t, v)).json()["data"]["reference"]
    await run(env, ref)
    view = (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).json()["data"]
    assert view["status"] == "SUCCESSFUL" and "being retrieved" in view["message"] and view["token_available"] is False
    assert (await get_token(env, t, ref)).status_code == 404 and "transaction.token_missing" in await audit_actions(env)
    assert await all_checks_ok(env)                     # the sale itself is settled correctly
    prov(env).tokens["sbx_1"] = "99887766554433221100"
    await sql(env, "UPDATE transactions SET completed_at = now() - interval '5 minutes', next_check_at = NULL")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert (await get_token(env, t, ref)).json()["data"]["token"] == "99887766554433221100"
    assert "transaction.token_recovered" in await audit_actions(env)

    ref2 = (await pay(env, t, v)).json()["data"]["reference"]
    await run(env, ref2)
    await sql(env, "UPDATE transactions SET completed_at = now() - interval '5 minutes', next_check_at = NULL, verify_attempts = 12 WHERE reference = :r", r=ref2)
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert "transaction.secret_unrecoverable" in await audit_actions(env)


async def test_expired_validation_blocks_new_payments_but_never_a_replay(env) -> None:
    t, _ = await customer(env, NGN(10_000))
    await seed_discos(env)
    v = await vid(env, t)
    first = await pay(env, t, v, key="idem-elec-0001")
    await env.redis.delete(f"meter:val:{v}")
    replay = await pay(env, t, v, key="idem-elec-0001")
    assert replay.status_code == 202 and replay.json()["data"]["reference"] == first.json()["data"]["reference"]
    fresh = await pay(env, t, v, key="idem-elec-0002")
    assert fresh.status_code == 409 and fresh.json()["error"]["code"] == "meter_validation_expired"
    assert await balance(env, t) == 1_000_000 - PRICE_E


async def test_price_changes_need_reconfirmation(env) -> None:
    t, _ = await customer(env, NGN(10_000))
    fin = await admin(env, "FINANCE", "08044440000")
    await seed_discos(env)
    v = await vid(env, t)
    rule = {"category": "ELECTRICITY", "method": "FACE_VALUE", "fee_kobo": 10_000, "note": "raise fee"}
    assert (await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json=rule)).json()["data"]["version"] == 2
    r = await pay(env, t, v)
    assert r.status_code == 409 and r.json()["error"]["code"] == "price_changed" and "5100.00" in r.json()["error"]["message"]
    assert await balance(env, t) == 1_000_000 and (await pay(env, t, v, price=510_000)).status_code == 202


async def test_electricity_stays_off_for_the_live_provider_until_verified(env) -> None:
    from app.modules.electricity.service import ElectricityDisabledError, ElectricityService
    live = env.app.state.settings.model_copy(update={"bill_provider": "inlomax", "inlomax_electricity_enabled": False})
    async with env.app.state.session_factory() as s:
        es = ElectricityService(s, env.redis, live, env.app.state.bill_providers)
        with pytest.raises(ElectricityDisabledError):
            await es.validate(SimpleNamespace(id=uuid.uuid4()), uuid.uuid4(), "PREPAID", METER)  # type: ignore[arg-type]
        es.settings = live.model_copy(update={"inlomax_electricity_enabled": True})
        es.check_enabled()


async def test_customer_responses_never_expose_cost_or_margin(env) -> None:
    t, _ = await customer(env, NGN(10_000))
    await seed_discos(env)
    v = await vid(env, t)
    ref = (await pay(env, t, v)).json()["data"]["reference"]
    await run(env, ref)
    blob = " ".join([(await env.client.get(f"{E}/discos", headers=bearer(t))).text,
                     (await validate(env, t)).text,
                     (await env.client.post(f"{E}/quote", headers=bearer(t), json={"validation_id": v, "amount_kobo": AMT})).text,
                     (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).text]).lower()
    for word in ("cost", "margin", "profit", "markup", "provider", "discount", "inlomax", "ik-pre", "497500"):
        assert word not in blob, word


async def test_profit_by_disco_and_service(env) -> None:
    t, _ = await customer(env, NGN(10_000))
    fin = await admin(env, "FINANCE", "08044440000")
    await seed_discos(env)
    ref = (await pay(env, t, await vid(env, t))).json()["data"]["reference"]
    await run(env, ref)
    by_disco = (await env.client.get(f"{F}/profit?group_by=disco", headers=bearer(fin))).json()["data"]
    assert [(g["key"], g["gross_profit"]["kobo"], g["gross_revenue"]["kobo"]) for g in by_disco["groups"]] == [("IKEJA", 7_500, PRICE_E)]
    by_service = (await env.client.get(f"{F}/profit?group_by=service", headers=bearer(fin))).json()["data"]["groups"]
    assert by_service[0]["key"] == "ELECTRICITY" and by_service[0]["gross_margin_pct"] == "1.49"
    assert (await env.client.get(f"{F}/ledger-checks", headers=bearer(fin))).json()["data"]["all_ok"]
