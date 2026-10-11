import uuid

from sqlalchemy import text

from app.core.money import Money
from app.modules.ledger.interface import SystemAccount
from tests.api.helpers import audit_actions, bearer, set_role, signup
from tests.api.test_airtime import FACE, PRICE, PIN, buy, customer, fund, run, sql, uid  # noqa: F401

P = "/api/v1/admin/pricing"
F = "/api/v1/admin/finance"
NGN = Money.from_naira


async def admin(env, role: str, phone="08099990000"):
    t = await signup(env, phone=phone)
    await set_role(env, "+234" + phone[1:], role)
    return t


RULE = {"category": "AIRTIME", "scope_key": "MTN", "method": "PERCENT_MARKUP", "markup_bps": 300, "note": "mtn promo margin"}


async def test_only_finance_and_super_admin_can_touch_pricing_or_profit(env) -> None:
    people = [("USER", "08011110000", False), ("SUPPORT", "08022220000", False), ("ADMIN", "08033330000", False),
              ("FINANCE", "08044440000", True), ("SUPER_ADMIN", "08055550000", True)]
    for role, phone, allowed in people:
        t = await admin(env, role, phone=phone)
        codes = [(await env.client.get(f"{P}/rules", headers=bearer(t))).status_code,
                 (await env.client.get(f"{P}/costs", headers=bearer(t))).status_code,
                 (await env.client.get(f"{F}/profit", headers=bearer(t))).status_code,
                 (await env.client.get(f"{F}/ledger-checks", headers=bearer(t))).status_code]
        assert all((c == 200) == allowed for c in codes), (role, codes)


async def test_preview_matches_the_spec_example(env) -> None:
    t = await admin(env, "FINANCE")
    r = await env.client.post(f"{P}/preview", headers=bearer(t), json={
        "provider_cost_kobo": 97_500, "method": "PERCENT_MARKUP", "markup_bps": 300, "discount_kobo": 500})
    d = r.json()["data"]
    assert (d["customer_price"], d["gross_profit"], d["margin_pct"], d["blocked"]) == ("999.25", "24.25", "2.43", False)
    blocked = (await env.client.post(f"{P}/preview", headers=bearer(t), json={
        "provider_cost_kobo": 98_000, "method": "CUSTOM_PRICE", "custom_price_kobo": 95_000})).json()["data"]
    assert blocked["blocked"] and blocked["block_reason"] == "Customer price is below provider cost."


async def test_rule_change_creates_new_version_audits_and_applies_to_new_sales_only(env) -> None:
    c, _ = await customer(env)
    old = await buy(env, c)
    assert old.status_code == 202
    t = await admin(env, "FINANCE")
    v1 = await env.client.post(f"{P}/rules", headers=bearer(t), json=RULE)
    v2 = await env.client.post(f"{P}/rules", headers=bearer(t), json={**RULE, "markup_bps": 400, "note": "raise mtn margin"})
    assert (v1.json()["data"]["version"], v2.json()["data"]["version"]) == (1, 2)
    assert v2.json()["data"]["markup_percent"] == "4.00"
    active = (await env.client.get(f"{P}/rules?category=AIRTIME", headers=bearer(t))).json()["data"]
    assert [x["scope_key"] for x in active].count("MTN") == 1       # one active rule per scope
    assert (await sql(env, "SELECT count(*) FROM pricing_rules"))[0][0] == 5   # airtime, data and electricity defaults, two MTN versions kept
    q = (await env.client.post("/api/v1/airtime/quote", headers=bearer(c), json={"network": "MTN", "amount_kobo": FACE})).json()["data"]
    assert q["price_kobo"] == 20_000        # 195.00 * 1.04 = 202.80, capped at the NGN 200 face value
    snap = (await sql(env, "SELECT customer_price_kobo, rule_version FROM pricing_snapshots"))[0]
    assert tuple(snap) == (PRICE, 1)        # yesterday's transaction keeps its original pricing snapshot
    assert "pricing.rule_changed" in await audit_actions(env)


async def test_subsidy_needs_super_admin_and_a_reason(env) -> None:
    fin = await admin(env, "FINANCE")
    body = {**RULE, "markup_bps": -500, "allow_subsidy": True, "subsidy_reason": "launch promo"}
    assert (await env.client.post(f"{P}/rules", headers=bearer(fin), json=body)).status_code == 403
    sup = await admin(env, "SUPER_ADMIN", phone="08055550000")
    assert (await env.client.post(f"{P}/rules", headers=bearer(sup), json={**body, "subsidy_reason": None})).status_code == 422
    assert (await env.client.post(f"{P}/rules", headers=bearer(sup), json=body)).status_code == 201


async def test_rule_input_validation_and_specificity(env) -> None:
    t = await admin(env, "FINANCE")
    for bad in ({**RULE, "markup_bps": None}, {**RULE, "markup_bps": 2.5}, {**RULE, "method": "CUSTOM_PRICE"},
                {**RULE, "discount_bps": 20_000}, {**RULE, "fee_kobo": -1}, {**RULE, "extra": 1}):
        assert (await env.client.post(f"{P}/rules", headers=bearer(t), json=bad)).status_code == 422, bad
    await env.client.post(f"{P}/rules", headers=bearer(t), json={**RULE, "scope_key": "GLO", "markup_bps": 100, "note": "glo only"})
    c, _ = await customer(env)
    glo = (await env.client.post("/api/v1/airtime/quote", headers=bearer(c), json={"network": "GLO", "amount_kobo": FACE})).json()["data"]
    assert glo["price_kobo"] == 19_392   # GLO cost 192.00 * 1.01: the network-specific rule beat the default


async def test_cost_sync_updates_audits_and_respects_manual_overrides(env) -> None:
    t = await admin(env, "FINANCE")
    await sql(env, "UPDATE provider_prices SET value = 100 WHERE scope_key = 'MTN'")
    await sql(env, "UPDATE provider_prices SET source='MANUAL', value = 111 WHERE scope_key = 'GLO'")
    r = (await env.client.post(f"{P}/costs/sync", headers=bearer(t))).json()["data"]
    assert r["updated"] == 1 and r["rejected"] == 0
    rows = {x["scope"]: x for x in (await env.client.get(f"{P}/costs", headers=bearer(t))).json()["data"]}
    assert rows["MTN"]["value"] == 250 and rows["MTN"]["source"] == "SYNCED" and rows["GLO"]["value"] == 111
    assert "provider_price.changed" in await audit_actions(env)


async def test_profit_dashboard_components_and_ledger_agree(env) -> None:
    c, _ = await customer(env, NGN(5000))
    refs = [(await buy(env, c, key=f"idem-profit-{i:03d}x")).json()["data"]["reference"] for i in range(3)]
    await run(env, refs[0])
    await run(env, refs[1])
    env.app.state.bill_providers["inlomax"].queue("failed")
    await run(env, refs[2])
    t = await admin(env, "FINANCE")
    d = (await env.client.get(f"{F}/profit?group_by=network", headers=bearer(t))).json()["data"]
    tot = d["totals"]
    assert tot["transactions"] == 2 and tot["gross_revenue"]["kobo"] == 2 * PRICE and tot["provider_cost"]["kobo"] == 2 * 19_500
    assert tot["gross_profit"]["kobo"] == 2 * 390 and tot["net_contribution"]["kobo"] == 2 * 390
    assert tot["gross_margin_pct"] == "1.96" and d["not_in_profit"]["failed_and_refunded_transactions"] == 1
    assert d["groups"][0]["key"] == "MTN" and d["groups"][0]["gross_profit"]["kobo"] == 780
    assert d["payment_processing_cost"] is None
    checks = (await env.client.get(f"{F}/ledger-checks", headers=bearer(t))).json()["data"]
    assert checks["all_ok"], checks
    assert len((await env.client.get(f"{F}/profit?group_by=date", headers=bearer(t))).json()["data"]["groups"]) == 1


async def test_admin_transaction_detail_hides_pricing_from_support(env) -> None:
    c, _ = await customer(env)
    ref = (await buy(env, c)).json()["data"]["reference"]
    await run(env, ref)
    sup, fin = await admin(env, "SUPPORT", phone="08022220000"), await admin(env, "FINANCE", phone="08044440000")
    s = (await env.client.get(f"/api/v1/admin/transactions/{ref}", headers=bearer(sup))).json()["data"]
    f = (await env.client.get(f"/api/v1/admin/transactions/{ref}", headers=bearer(fin))).json()["data"]
    assert "pricing" not in s and s["events"] and f["pricing"]["gross_profit"] == "3.90"
    assert f["pricing"]["actual_provider_cost"] == "195.00" and f["pricing"]["rule_version"] == 1
