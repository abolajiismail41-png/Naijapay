import dataclasses
import uuid

from app.core.money import Money
from app.modules.providers import prices as provider_prices
from app.modules.providers.base import DataRequest
from app.modules.ledger.interface import SystemAccount
from tests.api.helpers import audit_actions, bearer
from tests.api.test_admin_pricing_profit import F, P as PRICING, admin
from tests.api.test_airtime import (  # noqa: F401
    FACE, PIN, PRICE, all_checks_ok, balance, buy, customer, fund, net, prov, run, sql, status, token, uid,
)

NGN = Money.from_naira
D = "/api/v1/data"
ADM = "/api/v1/admin/data-plans"
MTN1 = 54_600     # plan 100: cost 530.00 + 3% = 545.90, rounded up to a whole naira


async def sync(env):
    async with env.app.state.session_factory() as s:
        return await provider_prices.sync_data_plans(s, prov(env), "inlomax")


async def pid(env, sid: str) -> str:
    return str((await sql(env, "SELECT id FROM data_plans WHERE provider_service_id=:s", s=sid))[0][0])


async def catalogue(env, *sids: str) -> None:
    await sync(env)
    for sid in sids:
        await sql(env, "UPDATE data_plans SET listed = true WHERE provider_service_id = :s", s=sid)


async def buy_data(env, t, plan_id: str, price: int, *, phone="08031234567", key=None, tok=None, confirm=False):
    return await env.client.post(D, json={"plan_id": plan_id, "phone": phone, "confirmed_price_kobo": price,
                                          "confirm_network": confirm},
                                 headers={**bearer(t), "X-PIN-Token": tok or await token(env, t),
                                          "Idempotency-Key": key or uuid.uuid4().hex})


async def plans(env, t, network="MTN"):
    return (await env.client.get(f"{D}/plans?network={network}", headers=bearer(t))).json()["data"]


async def test_new_plans_start_unlisted_and_hidden_from_customers(env) -> None:
    t, _ = await customer(env, NGN(0))
    rep = await sync(env)
    assert (rep.created, rep.updated, rep.deactivated, rep.suspicious) == (4, 0, 0, False)
    assert await plans(env, t) == [] and (await env.client.get(f"{D}/networks", headers=bearer(t))).json()["data"] == []
    rows = await sql(env, "SELECT kind, source, value FROM provider_prices WHERE category='DATA' ORDER BY value")
    assert tuple(rows[0]) == ("FIXED_KOBO", "SYNCED", 45_000) and "data_plan.discovered" in await audit_actions(env)
    again = await sync(env)
    assert (again.created, again.updated) == (0, 0)


async def test_admin_lists_plans_with_cost_and_margin_and_customers_see_price_only(env) -> None:
    t, _ = await customer(env, NGN(0))
    fin = await admin(env, "FINANCE", "08044440000")
    await sync(env)
    listing = (await env.client.get(ADM, headers=bearer(fin))).json()["data"]
    p1 = next(x for x in listing if x["provider_service_id"] == "100")
    assert len(listing) == 4 and not any(x["listed"] for x in listing)
    assert (p1["cost"], p1["customer_price"], p1["gross_profit"], p1["margin_pct"]) == ("530.00", "546.00", "16.00", "2.93")
    assert (await env.client.get(ADM, headers=bearer(t))).status_code == 403
    assert (await env.client.patch(f"{ADM}/{p1['id']}", headers=bearer(t), json={"listed": True})).status_code == 403
    assert (await env.client.patch(f"{ADM}/{p1['id']}", headers=bearer(fin), json={"listed": True})).status_code == 200
    items = await plans(env, t)
    assert [(i["name"], i["price_kobo"], i["price"]) for i in items] == [("1GB", MTN1, "546.00")]
    blob = (await env.client.get(f"{D}/plans?network=MTN", headers=bearer(t))).text.lower()
    for word in ("cost", "margin", "profit", "markup", "provider", "530.00"):
        assert word not in blob, word
    assert "data_plan.listing_changed" in await audit_actions(env)


async def test_a_plan_whose_price_would_be_below_cost_cannot_be_listed(env) -> None:
    fin = await admin(env, "FINANCE", "08044440000")
    await sync(env)
    rule = {"category": "DATA", "scope_key": "PLAN:100", "method": "CUSTOM_PRICE", "custom_price_kobo": 50_000, "note": "too cheap"}
    assert (await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json=rule)).status_code == 201
    r = await env.client.patch(f"{ADM}/{await pid(env, '100')}", headers=bearer(fin), json={"listed": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plan_not_sellable"
    listing = (await env.client.get(ADM, headers=bearer(fin))).json()["data"]
    assert next(x for x in listing if x["provider_service_id"] == "100")["price_blocked"] is True


async def test_data_purchase_success_flow_and_accounting(env) -> None:
    t, _ = await customer(env, NGN(2000))
    await catalogue(env, "100")
    plan = await pid(env, "100")
    q = (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": plan})).json()["data"]
    assert q["price_kobo"] == MTN1 and set(q) == {"plan_id", "network", "name", "validity", "price_kobo", "price"}
    r = await buy_data(env, t, plan, MTN1)
    d = r.json()["data"]
    assert r.status_code == 202 and d["status"] == "PENDING" and (d["plan"], d["validity"], d["network"]) == ("1GB", "30 Days", "MTN")
    ref = d["reference"]
    assert await balance(env, t) == 200_000 - MTN1 and await net(env, SystemAccount.REVENUE) == 0
    await run(env, ref)
    assert (await status(env, t, ref))["status"] == "SUCCESSFUL"
    req = prov(env).calls[0]
    assert isinstance(req, DataRequest) and (req.service_id, req.phone, req.request_id) == ("100", "08031234567", ref)
    snap = (await sql(env, "SELECT cost_kobo, markup_kobo, customer_price_kobo FROM pricing_snapshots"))[0]
    assert tuple(snap) == (53_000, 1_600, MTN1)
    assert tuple((await sql(env, "SELECT service_type, amount_kobo, provider_cost_kobo FROM transactions"))[0]) == ("DATA", MTN1, 53_000)
    assert await net(env, SystemAccount.REVENUE) == MTN1 and -await net(env, SystemAccount.PROVIDER_COST) == 53_000
    assert await all_checks_ok(env)


async def test_unlisted_inactive_or_unknown_plans_cannot_be_bought(env) -> None:
    t, _ = await customer(env)
    await sync(env)
    plan = await pid(env, "100")
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": plan})).status_code == 404
    await sql(env, "UPDATE data_plans SET listed = true")
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": plan})).status_code == 200
    await sql(env, "UPDATE data_plans SET active = false")
    r = await buy_data(env, t, plan, MTN1)
    assert r.status_code == 404 and r.json()["error"]["code"] == "plan_unavailable" and await balance(env, t) == 100_000
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": str(uuid.uuid4())})).status_code == 404


async def test_wrong_network_number_needs_confirmation_and_does_not_burn_the_pin(env) -> None:
    t, _ = await customer(env)
    await catalogue(env, "100")
    plan, tok = await pid(env, "100"), await token(env, t)
    r = await buy_data(env, t, plan, MTN1, phone="08021234567", tok=tok)         # 0802 is an Airtel prefix
    assert r.status_code == 409 and r.json()["error"]["code"] == "network_mismatch" and await balance(env, t) == 100_000
    assert (await buy_data(env, t, plan, MTN1, phone="08021234567", tok=tok, confirm=True)).status_code == 202
    air = await env.client.post("/api/v1/airtime", json={"network": "MTN", "phone": "08021234567", "amount_kobo": FACE,
                                                       "confirmed_price_kobo": PRICE},
                                headers={**bearer(t), "X-PIN-Token": await token(env, t), "Idempotency-Key": "air-mismatch-1"})
    assert air.status_code == 409 and air.json()["error"]["code"] == "network_mismatch"


async def test_price_change_requires_reconfirmation(env) -> None:
    t, _ = await customer(env)
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env, "100")
    plan = await pid(env, "100")
    rule = {"category": "DATA", "method": "PERCENT_MARKUP", "markup_bps": 500, "rounding_kobo": 100, "note": "raise margin"}
    assert (await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json=rule)).json()["data"]["version"] == 2
    r = await buy_data(env, t, plan, MTN1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "price_changed" and "557.00" in r.json()["error"]["message"]
    assert await balance(env, t) == 100_000 and (await buy_data(env, t, plan, 55_700)).status_code == 202


async def test_most_specific_pricing_rule_wins(env) -> None:
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env)
    for body in ({"scope_key": "MTN:SME", "markup_bps": 500, "note": "mtn sme"}, {"scope_key": "PLAN:101", "markup_bps": 200, "note": "plan 101"}):
        r = await env.client.post(f"{PRICING}/rules", headers=bearer(fin),
                                  json={"category": "DATA", "method": "PERCENT_MARKUP", "rounding_kobo": 100, **body})
        assert r.status_code == 201
    got = {x["provider_service_id"]: x["customer_price"] for x in (await env.client.get(ADM, headers=bearer(fin))).json()["data"]}
    assert got == {"100": "557.00",     # MTN:SME rule (5%)
                   "101": "1082.00",    # PLAN:101 rule (2%) beats MTN:SME
                   "200": "464.00",     # category default (3%)
                   "300": "1030.00"}


async def test_cost_change_flows_to_new_prices_not_old_snapshots_and_refreshes_the_cache(env) -> None:
    t, _ = await customer(env, NGN(2000))
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env, "100")
    plan = await pid(env, "100")
    ref = (await buy_data(env, t, plan, MTN1)).json()["data"]["reference"]
    await run(env, ref)
    assert (await plans(env, t))[0]["price_kobo"] == MTN1                       # now cached
    prov(env).plans[0] = dataclasses.replace(prov(env).plans[0], cost_kobo=60_000)
    r = (await env.client.post(f"{PRICING}/costs/sync", headers=bearer(fin))).json()["data"]
    assert r["data"]["updated"] == 1 and "provider_price.changed" in await audit_actions(env)
    assert (await plans(env, t))[0]["price_kobo"] == 61_800                    # cache dropped, 600.00 * 1.03
    snap = (await sql(env, "SELECT cost_kobo, customer_price_kobo FROM pricing_snapshots"))[0]
    assert tuple(snap) == (53_000, MTN1)                                       # yesterday's sale is untouched


async def test_manual_cost_override_survives_sync(env) -> None:
    t, _ = await customer(env, NGN(0))
    await catalogue(env, "100")
    await sql(env, "UPDATE provider_prices SET source='MANUAL', value = 70000 WHERE category='DATA' AND provider_service_id='100'")
    await sync(env)
    assert (await plans(env, t))[0]["price_kobo"] == 72_100                     # 700.00 * 1.03


async def test_vanished_plans_are_retired_but_a_bad_sync_cannot_empty_the_catalogue(env) -> None:
    t, _ = await customer(env)
    await catalogue(env, "100", "101", "200", "300")
    full = list(prov(env).plans)
    prov(env).plans = [p for p in full if p.provider_service_id != "101"]
    rep = await sync(env)
    assert rep.deactivated == 1 and not rep.suspicious
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": await pid(env, "101")})).status_code == 404
    prov(env).plans = []
    assert (await sync(env)).deactivated == 0 and "data_plan.sync_empty" in await audit_actions(env)
    prov(env).plans = [p for p in full if p.provider_service_id == "100"]
    rep = await sync(env)
    assert rep.suspicious and rep.deactivated == 0 and "data_plan.sync_suspicious" in await audit_actions(env)
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": await pid(env, "200")})).status_code == 200


async def test_stale_synced_cost_hides_the_plan_and_blocks_sales_and_listing(env) -> None:
    t, _ = await customer(env)
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env, "100")
    plan = await pid(env, "100")
    await sql(env, "UPDATE provider_prices SET synced_at = now() - interval '5 days' WHERE category='DATA'")
    assert await plans(env, t) == []
    assert (await env.client.post(f"{D}/quote", headers=bearer(t), json={"plan_id": plan})).status_code == 503
    assert (await env.client.patch(f"{ADM}/{plan}", headers=bearer(fin), json={"listed": True})).status_code == 422


async def test_data_failure_refunds_and_timeout_stays_unknown(env) -> None:
    t, _ = await customer(env, NGN(2000))
    await catalogue(env, "100")
    plan = await pid(env, "100")
    prov(env).queue("failed", "timeout")
    r1 = (await buy_data(env, t, plan, MTN1)).json()["data"]["reference"]
    r2 = (await buy_data(env, t, plan, MTN1)).json()["data"]["reference"]
    await run(env, r1)
    await run(env, r2)
    assert (await status(env, t, r1))["status"] == "REFUNDED" and (await status(env, t, r2))["status"] == "UNKNOWN"
    assert await balance(env, t) == 200_000 - MTN1 and await all_checks_ok(env)


async def test_profit_by_service_and_network_covers_airtime_and_data(env) -> None:
    t, _ = await customer(env, NGN(2000))
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env, "100")
    refs = [(await buy(env, t)).json()["data"]["reference"], (await buy_data(env, t, await pid(env, "100"), MTN1)).json()["data"]["reference"]]
    for ref in refs:
        await run(env, ref)
    by_service = {g["key"]: g for g in (await env.client.get(f"{F}/profit?group_by=service", headers=bearer(fin))).json()["data"]["groups"]}
    assert by_service["AIRTIME"]["gross_profit"]["kobo"] == 390 and by_service["DATA"]["gross_profit"]["kobo"] == 1_600
    by_net = (await env.client.get(f"{F}/profit?group_by=network", headers=bearer(fin))).json()["data"]
    assert [(g["key"], g["gross_profit"]["kobo"]) for g in by_net["groups"]] == [("MTN", 1_990)]
    assert by_net["totals"]["gross_profit"]["kobo"] == 1_990
    assert (await env.client.get(f"{F}/ledger-checks", headers=bearer(fin))).json()["data"]["all_ok"]


async def test_catalogue_cache_is_dropped_when_pricing_changes(env) -> None:
    t, _ = await customer(env, NGN(0))
    fin = await admin(env, "FINANCE", "08044440000")
    await catalogue(env, "100")
    assert (await plans(env, t))[0]["price_kobo"] == MTN1
    rule = {"category": "DATA", "method": "PERCENT_MARKUP", "markup_bps": 500, "rounding_kobo": 100, "note": "new margin"}
    await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json=rule)
    assert (await plans(env, t))[0]["price_kobo"] == 55_700
