import json
import uuid

from app.core.money import Money
from app.modules.providers.base import EducationRequest
from tests.api.helpers import audit_actions, bearer
from tests.api.test_admin_pricing_profit import F, P as PRICING, admin
from tests.api.test_airtime import (  # noqa: F401
    all_checks_ok, balance, customer, prov, run, sql, status, svc, token,
)

NGN = Money.from_naira
EDU = "/api/v1/education"
ADM = "/api/v1/admin/education/products"
WAEC_UNIT, NECO_UNIT = 522_000, 225_000      # provider cost 5,170 / 2,200 + NGN 50 fixed markup per pin


async def products(env, fin, list_them: bool = True) -> dict[str, str]:
    ids = {}
    for code, name, sid, cost in (("WAEC", "WAEC Result Checker PIN", "1", 517_000), ("NECO", "NECO Result Checker Token", "2", 220_000)):
        r = await env.client.post(ADM, headers=bearer(fin), json={"code": code, "name": name, "provider_service_id": sid, "cost_kobo": cost})
        assert r.status_code == 201, r.text
        ids[code] = r.json()["data"]["id"]
        if list_them:
            assert (await env.client.patch(f"{ADM}/{ids[code]}", headers=bearer(fin), json={"listed": True})).status_code == 200
    return ids


async def buy(env, t, product_id, quantity, price, *, key=None, tok=None):
    return await env.client.post(EDU, json={"product_id": product_id, "quantity": quantity, "confirmed_price_kobo": price},
                                 headers={**bearer(t), "X-PIN-Token": tok or await token(env, t), "Idempotency-Key": key or uuid.uuid4().hex})


async def get_pins(env, t, ref):
    return await env.client.get(f"{EDU}/{ref}/pins", headers=bearer(t))


async def setup(env, wallet=NGN(20_000)):
    t, _ = await customer(env, wallet)
    fin = await admin(env, "FINANCE", "08044440000")
    return t, fin, await products(env, fin)


async def test_admin_manages_products_and_sees_unit_margin(env) -> None:
    t, _ = await customer(env, NGN(0))
    fin = await admin(env, "FINANCE", "08044440000")
    body = {"code": "WAEC", "name": "WAEC Result Checker PIN", "provider_service_id": "1", "cost_kobo": 517_000}
    assert (await env.client.post(ADM, headers=bearer(t), json=body)).status_code == 403
    created = await env.client.post(ADM, headers=bearer(fin), json=body)
    assert created.status_code == 201 and (await env.client.post(ADM, headers=bearer(fin), json=body)).status_code == 409
    for bad in ({**body, "cost_kobo": 51.7}, {**body, "code": "waec"}, {**body, "extra": 1}, {**body, "max_quantity": 99}):
        assert (await env.client.post(ADM, headers=bearer(fin), json={**bad, "provider_service_id": "9"})).status_code == 422
    row = (await env.client.get(ADM, headers=bearer(fin))).json()["data"][0]
    assert (row["unit_cost"], row["unit_price"], row["unit_gross_profit"], row["unit_margin_pct"], row["listed"]) == (
        "5170.00", "5220.00", "50.00", "0.96", False)
    pid = created.json()["data"]["id"]
    assert (await env.client.get(f"{EDU}/products", headers=bearer(t))).json()["data"] == []     # unlisted: invisible
    assert (await env.client.patch(f"{ADM}/{pid}", headers=bearer(fin), json={"cost_kobo": 520_000})).status_code == 200
    assert "provider_price.changed" in await audit_actions(env)
    rule = {"category": "EDUCATION", "scope_key": "PRODUCT:1", "method": "CUSTOM_PRICE", "custom_price_kobo": 500_000, "note": "loss"}
    assert (await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json=rule)).status_code == 201
    r = await env.client.patch(f"{ADM}/{pid}", headers=bearer(fin), json={"listed": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "product_not_sellable"


async def test_customers_see_unit_prices_only(env) -> None:
    t, fin, ids = await setup(env, NGN(0))
    items = (await env.client.get(f"{EDU}/products", headers=bearer(t))).json()["data"]
    assert [(i["code"], i["unit_price_kobo"], i["max_quantity"]) for i in items] == [("NECO", NECO_UNIT, 5), ("WAEC", WAEC_UNIT, 5)] or \
           [(i["code"], i["unit_price_kobo"], i["max_quantity"]) for i in items] == [("WAEC", WAEC_UNIT, 5), ("NECO", NECO_UNIT, 5)]
    blob = (await env.client.get(f"{EDU}/products", headers=bearer(t))).text.lower()
    for word in ("cost", "margin", "profit", "markup", "provider", "517000", "5170"):
        assert word not in blob, word


async def test_quote_and_quantity_limits(env) -> None:
    t, fin, ids = await setup(env, NGN(0))
    q = (await env.client.post(f"{EDU}/quote", headers=bearer(t), json={"product_id": ids["WAEC"], "quantity": 3})).json()["data"]
    assert (q["price_kobo"], q["unit_price_kobo"], q["price"]) == (3 * WAEC_UNIT, WAEC_UNIT, "15660.00")
    for qty in (0, 6, "2", 2.5, -1):
        r = await env.client.post(f"{EDU}/quote", headers=bearer(t), json={"product_id": ids["WAEC"], "quantity": qty})
        assert r.status_code == 422, qty
    assert (await env.client.post(f"{EDU}/quote", headers=bearer(t), json={"product_id": str(uuid.uuid4()), "quantity": 1})).status_code == 404


async def test_purchase_encrypts_pins_and_serves_them_only_through_the_pins_endpoint(env) -> None:
    ta, fin, ids = await setup(env)
    tb, _ = await customer(env, NGN(0), phone="08087654321")
    r = await buy(env, ta, ids["WAEC"], 2, 2 * WAEC_UNIT)
    d = r.json()["data"]
    assert r.status_code == 202 and d["status"] == "PENDING" and (d["product"], d["quantity"]) == ("WAEC Result Checker PIN", 2)
    ref = d["reference"]
    assert await balance(env, ta) == 2_000_000 - 2 * WAEC_UNIT and (await get_pins(env, ta, ref)).status_code == 404
    await run(env, ref)
    view = await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(ta))
    assert view.json()["data"]["status"] == "SUCCESSFUL" and view.json()["data"]["pins_available"] is True
    out = (await get_pins(env, ta, ref)).json()["data"]
    assert (out["ordered"], out["received"], out["complete"]) == (2, 2, True) and all(p["pin"] and p["serial"] for p in out["pins"])
    assert out["pins"][0]["pin"] not in view.text and out["pins"][0]["pin"] not in (await env.client.get("/api/v1/transactions", headers=bearer(ta))).text
    cipher = (await sql(env, "SELECT pins_ciphertext FROM education_orders"))[0][0]
    assert cipher.startswith("v1:") and all(p["pin"] not in cipher for p in out["pins"])
    assert (await get_pins(env, tb, ref)).status_code == 404 and "pins.viewed" in await audit_actions(env)
    req = prov(env).calls[0]
    assert isinstance(req, EducationRequest) and (req.service_id, req.quantity) == ("1", 2)
    snap = (await sql(env, "SELECT cost_kobo, markup_kobo, customer_price_kobo, gross_profit_kobo FROM pricing_snapshots"))[0]
    assert tuple(snap) == (1_034_000, 10_000, 1_044_000, 10_000)
    assert await all_checks_ok(env)


async def test_a_reported_cost_that_looks_like_a_per_pin_figure_is_not_trusted(env) -> None:
    t, fin, ids = await setup(env)
    prov(env).cost_override = Money(517_000)           # provider "amount" = one pin although we bought three
    ref = (await buy(env, t, ids["WAEC"], 3, 3 * WAEC_UNIT)).json()["data"]["reference"]
    await run(env, ref)
    assert (await status(env, t, ref))["status"] == "SUCCESSFUL"
    assert (await sql(env, "SELECT provider_cost_kobo FROM transactions"))[0][0] == 1_551_000     # quoted cost booked
    meta = (await sql(env, "SELECT meta FROM audit_logs WHERE action='transaction.settlement_flags'"))[0][0]
    assert "cost_untrusted" in meta["flags"] and await all_checks_ok(env)


async def test_failure_refunds_and_a_timeout_is_resolved_manually_with_the_pins(env) -> None:
    t, fin, ids = await setup(env)
    prov(env).queue("failed", "timeout")
    r1 = (await buy(env, t, ids["NECO"], 1, NECO_UNIT)).json()["data"]["reference"]
    r2 = (await buy(env, t, ids["NECO"], 1, NECO_UNIT)).json()["data"]["reference"]
    await run(env, r1)
    await run(env, r2)
    assert (await status(env, t, r1))["status"] == "REFUNDED" and (await status(env, t, r2))["status"] == "UNKNOWN"
    assert await balance(env, t) == 2_000_000 - NECO_UNIT and await all_checks_ok(env)
    res = await env.client.post(f"/api/v1/admin/transactions/{r2}/resolve", headers=bearer(fin), json={
        "outcome": "SUCCESS", "provider_cost_kobo": 220_000, "pins": [["1111111111", "SRN-A"]], "note": "pin confirmed on provider dashboard"})
    assert res.status_code == 200
    got = (await get_pins(env, t, r2)).json()["data"]
    assert got["pins"] == [{"pin": "1111111111", "serial": "SRN-A"}] and got["complete"] is True and await all_checks_ok(env)


async def test_partial_and_missing_pins_are_flagged_recovered_and_escalated(env) -> None:
    t, fin, ids = await setup(env)
    prov(env).queue("partial", "no_pins", "no_pins")
    full = (("5555555555", "SRN-F1"), ("6666666666", "SRN-F2"))
    ref = (await buy(env, t, ids["WAEC"], 2, 2 * WAEC_UNIT)).json()["data"]["reference"]
    await run(env, ref)
    view = (await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).json()["data"]
    assert view["status"] == "SUCCESSFUL" and "Some PINs are ready" in view["message"] and "transaction.pins_partial" in await audit_actions(env)
    part = (await get_pins(env, t, ref)).json()["data"]
    assert (part["received"], part["complete"]) == (1, False) and await all_checks_ok(env)
    prov(env).pins["sbx_1"] = full
    await sql(env, "UPDATE transactions SET completed_at = now() - interval '5 minutes', next_check_at = NULL")
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    done = (await get_pins(env, t, ref)).json()["data"]
    assert done["complete"] is True and [p["pin"] for p in done["pins"]] == ["5555555555", "6666666666"]
    assert "transaction.pins_recovered" in await audit_actions(env)

    ref2 = (await buy(env, t, ids["NECO"], 1, NECO_UNIT)).json()["data"]["reference"]
    await run(env, ref2)
    v2 = (await env.client.get(f"/api/v1/transactions/{ref2}", headers=bearer(t))).json()["data"]
    assert "being retrieved" in v2["message"] and (await get_pins(env, t, ref2)).status_code == 404 and "transaction.pins_missing" in await audit_actions(env)
    await sql(env, "UPDATE transactions SET completed_at = now() - interval '5 minutes', next_check_at = NULL, verify_attempts = 12 WHERE reference=:r", r=ref2)
    async with env.app.state.session_factory() as s:
        await svc(env, s).sweep()
    assert "transaction.secret_unrecoverable" in await audit_actions(env)


async def test_markup_rules_by_product_and_price_confirmation(env) -> None:
    t, fin, ids = await setup(env)
    base = {"category": "EDUCATION", "method": "PERCENT_MARKUP", "markup_bps": 200, "rounding_kobo": 100}
    assert (await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json={**base, "scope_key": "WAEC", "note": "waec 2%"})).status_code == 201
    unit = {i["code"]: i["unit_price_kobo"] for i in (await env.client.get(f"{EDU}/products", headers=bearer(t))).json()["data"]}
    assert unit == {"WAEC": 527_400, "NECO": NECO_UNIT}            # 5,170 + 2% = 5,273.40 rounded up; NECO keeps the default
    stale = await buy(env, t, ids["WAEC"], 1, WAEC_UNIT)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "price_changed" and "5274.00" in stale.json()["error"]["message"]
    await env.client.post(f"{PRICING}/rules", headers=bearer(fin), json={
        "category": "EDUCATION", "method": "FIXED_MARKUP", "markup_kobo": 10_000, "scope_key": "PRODUCT:1", "note": "waec fixed"})
    unit = {i["code"]: i["unit_price_kobo"] for i in (await env.client.get(f"{EDU}/products", headers=bearer(t))).json()["data"]}
    assert unit["WAEC"] == 527_000                                  # the product-specific rule beats the exam-code rule
    assert await balance(env, t) == 2_000_000 and (await buy(env, t, ids["WAEC"], 1, 527_000)).status_code == 202


async def test_idempotency_and_double_spend(env) -> None:
    t, fin, ids = await setup(env, Money(WAEC_UNIT))
    a = await buy(env, t, ids["WAEC"], 1, WAEC_UNIT, key="idem-pins-0001")
    b = await buy(env, t, ids["WAEC"], 1, WAEC_UNIT, key="idem-pins-0001")
    assert a.json()["data"]["reference"] == b.json()["data"]["reference"] and await balance(env, t) == 0
    assert (await buy(env, t, ids["WAEC"], 2, 2 * WAEC_UNIT, key="idem-pins-0001")).status_code == 409
    t2, _ = await customer(env, Money(WAEC_UNIT), phone="08087654321")
    import asyncio
    toks = [await token(env, t2) for _ in range(2)]
    rs = await asyncio.gather(*[buy(env, t2, ids["WAEC"], 1, WAEC_UNIT, tok=k) for k in toks])
    assert sorted(r.status_code for r in rs) == [202, 422] and await balance(env, t2) == 0


async def test_profit_by_product_and_customer_views_stay_clean(env) -> None:
    t, fin, ids = await setup(env)
    ref = (await buy(env, t, ids["WAEC"], 2, 2 * WAEC_UNIT)).json()["data"]["reference"]
    await run(env, ref)
    by_product = (await env.client.get(f"{F}/profit?group_by=product", headers=bearer(fin))).json()["data"]["groups"]
    assert [(g["key"], g["gross_profit"]["kobo"], g["gross_revenue"]["kobo"]) for g in by_product] == [("WAEC", 10_000, 1_044_000)]
    assert (await env.client.get(f"{F}/profit?group_by=service", headers=bearer(fin))).json()["data"]["groups"][0]["key"] == "EDUCATION"
    assert (await env.client.get(f"{F}/ledger-checks", headers=bearer(fin))).json()["data"]["all_ok"]
    blob = json.dumps([(await env.client.get(f"/api/v1/transactions/{ref}", headers=bearer(t))).json(),
                       (await env.client.get(f"{EDU}/products", headers=bearer(t))).json()]).lower()
    for word in ("cost", "margin", "profit", "markup", "provider", "inlomax", "517000", "1034000"):
        assert word not in blob, word
