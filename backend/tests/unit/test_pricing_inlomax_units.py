import json
from decimal import Decimal

import httpx
import pytest

from app.core.money import Money
from app.modules.providers.base import AirtimeRequest, Outcome
from app.modules.providers.errors import ProviderUnavailableError
from app.modules.providers.inlomax import InlomaxProvider
from app.modules.services.errors import PricingBlockedError
from app.modules.services.pricing import RuleParams, compute
from app.modules.transactions.state import ALLOWED, InvalidTransitionError, TxnStatus, transition

NGN = Money.from_naira


def pct(bps: int, **kw) -> RuleParams:
    return RuleParams("PERCENT_MARKUP", markup_bps=bps, **kw)


def test_spec_example_preview_is_exact() -> None:
    b = compute(NGN(975), pct(300, discount_kobo=500), enforce=False)
    assert (b.customer_price, b.gross_profit) == (NGN("999.25"), NGN("24.25"))
    assert str(b.margin_pct) == "2.43" and b.gross_profit_before_discount == NGN("29.25")


def test_fixed_markup_example() -> None:
    b = compute(NGN(975), RuleParams("FIXED_MARKUP", markup_kobo=2500))
    assert (b.customer_price, b.gross_profit) == (NGN(1000), NGN(25))


def test_custom_price_and_fee_and_percent_discount() -> None:
    b = compute(NGN(900), RuleParams("CUSTOM_PRICE", custom_price_kobo=100_000, fee_kobo=5_000, discount_bps=1000))
    assert b.list_price == NGN(1050) and b.discount == NGN(105) and b.customer_price == NGN(945)
    assert b.markup == NGN(100)


def test_below_cost_is_blocked_unless_subsidy_allowed() -> None:
    with pytest.raises(PricingBlockedError):
        compute(NGN(980), RuleParams("CUSTOM_PRICE", custom_price_kobo=95_000))
    with pytest.raises(PricingBlockedError):  # a discount can push a healthy price under cost
        compute(NGN(975), pct(100, discount_kobo=5_000))
    b = compute(NGN(980), RuleParams("CUSTOM_PRICE", custom_price_kobo=95_000, allow_subsidy=True))
    assert b.below_cost and b.gross_profit == NGN(-30)


def test_airtime_ceiling_caps_at_face_value_and_records_it() -> None:
    b = compute(NGN("195"), RuleParams("PERCENT_MARKUP", markup_bps=500, cap_at_face=True), face=NGN(200))
    assert b.capped and b.customer_price == NGN(200)
    assert b.markup + b.cost + b.fee == b.list_price


def test_referral_commission_only_from_real_margin() -> None:
    b = compute(NGN(975), pct(300, referral_bps=5000), referral_applicable=True)
    assert b.referral_commission == b.gross_profit.percent(Decimal(50)) and b.net_contribution < b.gross_profit
    assert compute(NGN(975), pct(300, referral_bps=5000)).referral_commission == Money(0)


def test_no_float_leakage_and_determinism() -> None:
    a = compute(Money(333_333), pct(173), referral_applicable=True)
    assert a == compute(Money(333_333), pct(173), referral_applicable=True)
    assert all(isinstance(getattr(a, f).kobo, int) for f in ("cost", "markup", "customer_price", "gross_profit"))


def test_state_machine_blocks_illegal_moves() -> None:
    class T:  # minimal stand-in
        reference, id, status = "txn_x", None, TxnStatus.SUCCESSFUL.value

    class Db:
        def add(self, _): ...
    for bad in (TxnStatus.REFUNDED, TxnStatus.FAILED, TxnStatus.PROCESSING):
        with pytest.raises(InvalidTransitionError):
            transition(Db(), T(), bad)  # type: ignore[arg-type]
    assert ALLOWED[TxnStatus.UNKNOWN] >= {TxnStatus.SUCCESSFUL, TxnStatus.FAILED}
    assert not ALLOWED[TxnStatus.REFUNDED] and TxnStatus.REFUNDED not in ALLOWED[TxnStatus.UNKNOWN]


def _prov(handler) -> InlomaxProvider:
    return InlomaxProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "key123", "https://x.test/api")


REQ = AirtimeRequest("txn_abc", "1", "MTN", "0903837261", NGN(200))
SUCCESS = ('{"status":"success","message":"ok","data":{"type":"airtime","amount":200,"amountCharged":195.5,'
           '"reference":"INL|ABC","phoneNumber":"0903837261","network":"MTN","status":"success"}}')


async def test_purchase_request_matches_docs_and_success_parses_exact_cost() -> None:
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(url=str(r.url), auth=r.headers["authorization"], body=json.loads(r.content))
        return httpx.Response(200, text=SUCCESS)

    res = await _prov(handler).purchase_airtime(REQ)
    assert seen["url"] == "https://x.test/api/airtime" and seen["auth"] == "Token key123"
    assert seen["body"] == {"serviceID": "1", "amount": 200, "mobileNumber": "0903837261", "request-id": "txn_abc"}
    assert res.outcome is Outcome.SUCCESS and res.provider_reference == "INL|ABC"
    assert res.amount_charged == Money(19_550) and res.amount == NGN(200)  # Decimal parsing, no float error


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"status":"failed","message":"Insufficient balance","data":{}}', Outcome.FAILED),
    (200, '{"status":"success","data":{"status":"processing","reference":"R1"}}', Outcome.PROCESSING),
    (400, '{"status":"failed","message":"Invalid serviceID"}', Outcome.FAILED),
    (500, "oops", Outcome.UNKNOWN), (502, "", Outcome.UNKNOWN), (200, "not json", Outcome.UNKNOWN),
    (200, "[1,2]", Outcome.UNKNOWN), (200, '{"status":"mystery"}', Outcome.UNKNOWN), (404, "<html>", Outcome.UNKNOWN),
])
async def test_outcome_mapping_never_turns_ambiguity_into_failure(status: int, body: str, expected: Outcome) -> None:
    assert (await _prov(lambda r: httpx.Response(status, text=body)).purchase_airtime(REQ)).outcome is expected


async def test_timeout_is_unknown_and_purchase_is_never_retried() -> None:
    calls = {"n": 0}

    def boom(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")
    res = await _prov(boom).purchase_airtime(REQ)
    assert res.outcome is Outcome.UNKNOWN and calls["n"] == 1


async def test_status_balance_and_cost_sync_parsing() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/transaction"):
            assert json.loads(r.content) == {"reference": "INL|ABC"}
            return httpx.Response(200, text=SUCCESS)
        if r.url.path.endswith("/balance"):
            return httpx.Response(200, text='{"status":"success","data":{"funds":2393.5}}')
        return httpx.Response(200, text='{"status":"success","data":{"airtime":[{"network":"MTN","serviceID":"1","discount":"2.5"},'
                                       '{"network":"Bad","serviceID":"9","discount":"x"}]}}')
    p = _prov(handler)
    assert (await p.fetch_status("INL|ABC")).outcome is Outcome.SUCCESS
    assert await p.balance() == Money(239_350)
    costs = await p.fetch_costs()
    assert [(c.scope_key, c.provider_service_id, c.value) for c in costs] == [("MTN", "1", 250)]


async def test_balance_failure_raises() -> None:
    with pytest.raises(ProviderUnavailableError):
        await _prov(lambda r: httpx.Response(503)).balance()


# ---------------- Phase 6: rounding, data adapter, network guard ----------------
def test_rounding_goes_up_to_whole_naira_and_never_erodes_margin() -> None:
    b = compute(Money(53_000), pct(300, rounding_kobo=100))
    assert b.customer_price == Money(54_600) and b.markup == Money(1_600) and b.gross_profit == Money(1_600)
    assert b.list_price - b.discount == b.customer_price and b.cost + b.markup + b.fee == b.list_price
    exact = compute(Money(100_000), pct(300, rounding_kobo=100))
    assert exact.customer_price == Money(103_000)


def test_rounding_with_discount_and_ceiling() -> None:
    b = compute(Money(53_000), pct(300, rounding_kobo=100, discount_kobo=150))
    assert b.customer_price == Money(54_500) and b.discount == Money(150)      # (54,590 - 150) rounds up to 54,500
    capped = compute(NGN(195), RuleParams("PERCENT_MARKUP", markup_bps=500, rounding_kobo=1000, cap_at_face=True), face=NGN(200))
    assert capped.customer_price == NGN(200) and capped.capped


async def test_data_purchase_request_and_cost_from_amount_field() -> None:
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(url=str(r.url), body=json.loads(r.content))
        return httpx.Response(200, text='{"status":"success","message":"ok","data":{"type":"data","reference":"INL|N1",'
                                        '"amount":1000,"dataPlan":"5GB","dataType":"SME","network":"MTN","status":"success"}}')
    from app.modules.providers.base import DataRequest
    res = await _prov(handler).purchase_data(DataRequest("txn_d1", "100", "MTN", "0903837261"))
    assert seen["url"] == "https://x.test/api/data"
    assert seen["body"] == {"serviceID": "100", "mobileNumber": "0903837261", "request-id": "txn_d1"}
    assert res.outcome is Outcome.SUCCESS and res.amount_charged == NGN(1000) and res.amount is None
    assert res.provider_reference == "INL|N1"


async def test_data_ambiguity_is_unknown_and_failure_is_definite() -> None:
    from app.modules.providers.base import DataRequest
    req = DataRequest("txn_d2", "100", "MTN", "0903837261")
    assert (await _prov(lambda r: httpx.Response(504)).purchase_data(req)).outcome is Outcome.UNKNOWN
    assert (await _prov(lambda r: httpx.Response(200, text='{"status":"failed","message":"x"}')).purchase_data(req)).outcome is Outcome.FAILED

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("t")
    assert (await _prov(boom).purchase_data(req)).outcome is Outcome.UNKNOWN


async def test_data_plan_parsing_accepts_both_shapes_and_skips_bad_rows() -> None:
    rows = [{"serviceID": "35", "network": "MTN", "dataPlan": "500MB", "amount": "300.00", "dataType": "CORPORATE GIFTING", "validity": "30 Days"},
            {"serviceID": "23", "network": "glo", "dataPlan": "1GB", "amount": "500.00", "dataType": "GIFTING", "validity": "30 Days"},
            {"serviceID": "9", "network": "MTN", "dataPlan": "bad", "amount": "free"}, {"nope": 1}]
    for body in ({"status": "success", "data": {"dataPlans": rows}}, {"status": "success", "data": rows}):
        plans = await _prov(lambda r, b=body: httpx.Response(200, text=json.dumps(b))).fetch_data_plans()
        assert [(p.provider_service_id, p.network, p.name, p.cost_kobo) for p in plans] == [
            ("35", "MTN", "500MB", 30_000), ("23", "GLO", "1GB", 50_000)]


def test_network_guard_is_a_confirmable_warning_not_a_block() -> None:
    from app.modules.transactions.networks import NetworkMismatchError, check_network, guess_network
    assert guess_network("+2348031234567") == "MTN" and guess_network("+2348021234567") == "AIRTEL"
    assert guess_network("+2348051234567") == "GLO" and guess_network("+2348091234567") == "9MOBILE"
    check_network("+2348031234567", "MTN", False)
    with pytest.raises(NetworkMismatchError):
        check_network("+2348021234567", "MTN", False)
    check_network("+2348021234567", "MTN", True)          # customer confirmed (ported number)
    check_network("+2347021234567", "MTN", False)         # unknown prefix: no opinion


# ---------------- Phase 7: electricity ----------------
def test_face_value_pricing_example_and_guards() -> None:
    b = compute(NGN(4975), RuleParams("FACE_VALUE", fee_kobo=5_000), face=NGN(5000))
    assert (b.customer_price, b.markup, b.gross_profit, b.fee) == (NGN(5050), NGN(25), NGN(75), NGN(50))
    assert b.list_price == NGN(5050) and str(b.margin_pct) == "1.49"
    with pytest.raises(ValueError):
        compute(NGN(4975), RuleParams("FACE_VALUE"), face=None)
    with pytest.raises(PricingBlockedError):   # provider charging more than the product value, fee too small
        compute(NGN(5100), RuleParams("FACE_VALUE", fee_kobo=5_000), face=NGN(5000))


def test_field_encryption_is_authenticated_and_bound_to_its_record() -> None:
    from app.core.crypto import decrypt, encrypt
    blob = encrypt("k1", "1234-5678-9012", "txn_a")
    assert blob.startswith("v1:") and "1234" not in blob and blob != encrypt("k1", "1234-5678-9012", "txn_a")
    assert decrypt("k1", blob, "txn_a") == "1234-5678-9012"
    for args in (("k2", blob, "txn_a"), ("k1", blob, "txn_b"), ("k1", blob[:-4] + "AAAA", "txn_a"), ("k1", "v9:xx", "txn_a")):
        with pytest.raises(ValueError):
            decrypt(*args)


def test_meter_masking() -> None:
    from app.modules.transactions.views import mask
    assert mask("12345678901") == "*******8901" and mask("123") == "123"


def _elec(handler) -> InlomaxProvider:
    return _prov(handler)


async def test_meter_validation_parsing_is_defensive() -> None:
    from app.modules.providers.errors import MeterInvalidError
    ok = '{"status":"success","data":{"customerName":"ADA OBI","address":"1 Test St","minimumAmount":500}}'
    info = await _elec(lambda r: httpx.Response(200, text=ok)).validate_meter("ikeja", "1", "12345678901", "PREPAID")
    assert (info.customer_name, info.address, info.min_amount) == ("ADA OBI", "1 Test St", NGN(500))
    with pytest.raises(MeterInvalidError):
        await _elec(lambda r: httpx.Response(200, text='{"status":"failed","message":"not found"}')).validate_meter("ikeja", "1", "1", "PREPAID")
    for resp in (httpx.Response(503), httpx.Response(200, text="junk"), httpx.Response(200, text='{"status":"success","data":{}}')):
        with pytest.raises(ProviderUnavailableError):    # unclear answers never become "invalid meter"
            await _elec(lambda r, x=resp: x).validate_meter("ikeja", "1", "12345678901", "PREPAID")


async def test_electricity_purchase_body_and_token_extraction() -> None:
    from app.modules.providers.base import ElectricityRequest
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(path=r.url.path, body=json.loads(r.content))
        return httpx.Response(200, text='{"status":"success","data":{"status":"success","reference":"INL|E1","amount":5000,'
                                        '"amountCharged":4975,"token":"Token : 1234-5678-9012-3456","units":"31.2"}}')
    req = ElectricityRequest("txn_e1", "7", "ikeja", "PREPAID", "12345678901", NGN(5000))
    res = await _elec(handler).purchase_electricity(req)
    assert seen["path"] == "/api/electricity"
    assert seen["body"] == {"serviceID": "7", "amount": 5000, "meterNumber": "12345678901", "request-id": "txn_e1"}
    assert res.outcome is Outcome.SUCCESS and res.token == "1234-5678-9012-3456" and res.units == "31.2"
    assert res.amount_charged == NGN(4975) and res.provider_reference == "INL|E1"
    no_token = await _elec(lambda r: httpx.Response(200, text='{"status":"success","data":{"status":"success","reference":"R","amount":5000}}')).purchase_electricity(req)
    assert no_token.outcome is Outcome.SUCCESS and no_token.token is None
    assert (await _elec(lambda r: httpx.Response(502)).purchase_electricity(req)).outcome is Outcome.UNKNOWN


async def test_electricity_catalogue_parsing_skips_what_it_cannot_understand() -> None:
    rows = [{"serviceID": "7", "disco": "Ikeja Electric Prepaid", "discount": "0.5"},
            {"serviceID": "8", "name": "Eko Electricity", "meterType": "postpaid", "discount": "1"},
            {"serviceID": "9", "disco": "Mystery"}, {"serviceID": "10", "disco": "Abuja Prepaid", "discount": "x"}]
    body = {"status": "success", "data": {"electricity": rows}}
    got = await _prov(lambda r: httpx.Response(200, text=json.dumps(body))).fetch_electricity()
    assert [(e.disco_code, e.meter_type, e.service_id, e.discount_bps) for e in got] == [
        ("IKEJA", "PREPAID", "7", 50), ("EKO", "POSTPAID", "8", 100)]


# ---------------- Phase 8: exam pins ----------------
def test_quantity_scaling_keeps_per_unit_rules_per_unit() -> None:
    from app.modules.services.pricing import compute_scaled
    rule = RuleParams("FIXED_MARKUP", markup_kobo=5_000, rounding_kobo=100)
    one, three = compute_scaled(Money(517_000), rule, quantity=1), compute_scaled(Money(517_000), rule, quantity=3)
    assert one == compute(Money(517_000), rule)
    assert (three.customer_price, three.cost, three.markup, three.gross_profit) == (Money(1_566_000), Money(1_551_000), Money(15_000), Money(15_000))
    assert three.margin_pct == one.margin_pct == Decimal("0.96")
    with pytest.raises(PricingBlockedError):   # margin protection still applies per unit
        compute_scaled(Money(517_000), RuleParams("CUSTOM_PRICE", custom_price_kobo=500_000), quantity=3)
    with pytest.raises(TypeError):
        Money(5).times(1.5)  # type: ignore[arg-type]


async def test_exam_pin_purchase_parses_padded_pins_and_cost_from_amount() -> None:
    from app.modules.providers.base import EducationRequest
    seen = {}
    body = ('{"status":"success","message":"WAEC pin purchase successful","data":{"type":"education","educationType":"waec",'
            '"amount":6700,"pins":[{"pin":" 3635674583","serialNo":" SRN7HFSDSFUE"},{"pin":"754643565 ","serialNo":"SRN75JFHASC"},'
            '{"serialNo":"no pin"}],"quantity":"3","status":"success"}}')

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(path=r.url.path, body=json.loads(r.content))
        return httpx.Response(200, text=body)
    res = await _prov(handler).purchase_education(EducationRequest("txn_p1", "1", 3))
    assert seen["path"] == "/api/education" and seen["body"] == {"serviceID": "1", "quantity": 3, "request-id": "txn_p1"}
    assert res.outcome is Outcome.SUCCESS and res.pins == (("3635674583", "SRN7HFSDSFUE"), ("754643565", "SRN75JFHASC"))
    assert res.amount_charged == NGN(6700) and res.amount is None
    assert res.provider_reference is None      # the documented education response carries no reference
    req = EducationRequest("txn_p1", "1", 1)
    for resp in (httpx.Response(200, text=body[:-40]), httpx.Response(502), httpx.Response(200, text='{"status":"processing"}')):
        r = await _prov(lambda r_, x=resp: x).purchase_education(req)
        assert r.outcome in (Outcome.UNKNOWN, Outcome.PROCESSING) and r.pins is None
    failed = await _prov(lambda r_: httpx.Response(200, text='{"status":"failed","message":"no stock"}')).purchase_education(req)
    assert failed.outcome is Outcome.FAILED
