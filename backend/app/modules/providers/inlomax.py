import json
import logging
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.money import Money
from app.modules.providers.base import (
    AirtimeRequest, CostEntry, DataPlanEntry, DataRequest, ElectricityEntry, ElectricityRequest, EducationRequest, MeterInfo,
    Outcome, ProviderResult, TVCustomerInfo, TVPlanEntry, TVRequest,
)
from app.modules.providers.errors import MeterInvalidError, ProviderUnavailableError, SmartcardInvalidError

log = logging.getLogger(__name__)
_NOISE_WORDS = {"prepaid", "postpaid", "electric", "electricity", "distribution", "company", "payment", "plc", "disco"}
_OUTCOMES = {"success": Outcome.SUCCESS, "failed": Outcome.FAILED, "processing": Outcome.PROCESSING}

# Exam PINs. Inlomax documents data.pins[] of {pin, serialNo}, but the live shape is not guaranteed, so the
# parser also accepts alternative key names, a list of bare strings, and a single top-level PIN.
_PIN_KEYS = ("pin", "PIN", "Pin", "pinCode", "pin_code", "code", "voucher")
_SERIAL_KEYS = ("serialNo", "serialNumber", "serial_no", "serial", "serialno", "SerialNo", "sn")
_MAX_PINS = 100  # matches the largest quantity the education API accepts


def _money(value: Any) -> Money | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value).replace(",", ""))
        return Money.from_naira(d) if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _first_of(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    """First non-empty string/int value among `keys` (bools are not values), stripped."""
    for k in keys:
        v = data.get(k)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            return str(v).strip()
    return ""


def _first(data: dict[str, Any], *keys: str) -> str:
    return _first_of(data, keys)


def _token(data: dict[str, Any]) -> str | None:
    raw = _first(data, "token", "Token", "tokenCode", "pin")
    return (raw.split(":", 1)[1].strip() if raw.lower().startswith("token") and ":" in raw else raw)[:200] or None


def _pins(data: dict[str, Any]) -> tuple[tuple[str, str], ...] | None:
    """Return ((pin, serial), ...) or None when the response carries no PINs.

    Accepts: pins as a list of objects, a list of bare strings/ints, a dict of PINs, a single string,
    or a single PIN at the top level of `data`. Values are stripped because the provider pads them.
    """
    rows: Any = data.get("pins")
    if rows is None and any(k in data for k in _PIN_KEYS):
        rows = [data]  # one PIN at the top level
    if isinstance(rows, dict):
        rows = list(rows.values())
    if isinstance(rows, (str, int)) and not isinstance(rows, bool) and str(rows).strip():
        rows = [str(rows)]
    if not isinstance(rows, list):
        return None
    out: list[tuple[str, str]] = []
    for r in rows[:_MAX_PINS]:
        if isinstance(r, (str, int)) and not isinstance(r, bool):
            pin, serial = str(r).strip(), ""
        elif isinstance(r, dict):
            pin, serial = _first_of(r, _PIN_KEYS), _first_of(r, _SERIAL_KEYS)
        else:
            continue
        if pin:
            out.append((pin[:60], serial[:60]))
    return tuple(out) or None


def _log_education_shape(payload: dict[str, Any], data: dict[str, Any]) -> None:
    """Log the STRUCTURE of an exam-pin response (key names and counts), never any value.

    This is how an unexpected provider shape is diagnosed without writing PINs to the logs.
    """
    rows = data.get("pins")
    first = rows[0] if isinstance(rows, list) and rows else None
    log.info(
        "inlomax_education_shape top_keys=%s data_keys=%s pins_type=%s pins_count=%s first_item=%s",
        sorted(str(k) for k in payload.keys()), sorted(str(k) for k in data.keys()),
        type(rows).__name__, len(rows) if isinstance(rows, list) else None,
        sorted(str(k) for k in first.keys()) if isinstance(first, dict) else type(first).__name__,
    )


def _parse(text: str) -> dict[str, Any] | None:
    try:  # parse_float=Decimal keeps naira amounts exact
        payload = json.loads(text, parse_float=Decimal)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


class InlomaxProvider:
    """Adapter for https://inlomax.com/docs. Never retries a purchase: its request-id de-duplication
    is undocumented, so a blind retry could deliver twice."""

    code = "inlomax"
    can_query_by_request_id = False  # /transaction only documents lookup by Inlomax's own reference

    def __init__(self, client: httpx.AsyncClient, api_key: str, base_url: str, *,
                 electricity_path: str = "/electricity", meter_verify_path: str = "/validatemeter") -> None:
        self._c, self._key, self._base = client, api_key, base_url.rstrip("/")
        self._elec_path, self._verify_path = electricity_path, meter_verify_path

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._key}", "Content-Type": "application/json"}

    @staticmethod
    def _to_result(resp: httpx.Response, *, log_shape: bool = False) -> ProviderResult:
        if resp.status_code >= 500:
            return ProviderResult(Outcome.UNKNOWN, message=f"http_{resp.status_code}", http_status=resp.status_code)
        payload = _parse(resp.text)
        if payload is None:
            return ProviderResult(Outcome.UNKNOWN, message="unparseable_response", http_status=resp.status_code)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if log_shape:
            _log_education_shape(payload, data)
        raw = str(data.get("status") or payload.get("status") or "").lower()
        outcome = _OUTCOMES.get(raw, Outcome.UNKNOWN)  # anything unrecognised is NOT treated as failure
        # Inlomax's own reference. Some responses carry it inside `data`, others at the top level; without
        # it a later status check or PIN recovery has nothing to look up.
        ref = data.get("reference") if data.get("reference") else payload.get("reference")
        return ProviderResult(
            outcome, str(ref)[:80] if isinstance(ref, (str, int)) and not isinstance(ref, bool) and str(ref) else None,
            _money(data.get("amount")), _money(data.get("amountCharged")),
            str(payload.get("message", ""))[:200] if outcome is not Outcome.SUCCESS else "", resp.status_code,
            token=_token(data), units=_first(data, "units", "unit", "kwh")[:20] or None, pins=_pins(data))

    async def purchase_airtime(self, req: AirtimeRequest) -> ProviderResult:
        if req.amount.kobo % 100:
            raise ValueError("airtime amount must be whole naira")
        body = {"serviceID": req.service_id, "amount": req.amount.kobo // 100,
                "mobileNumber": req.phone, "request-id": req.request_id}
        try:
            resp = await self._c.post(f"{self._base}/airtime", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        return self._to_result(resp)

    async def purchase_data(self, req: DataRequest) -> ProviderResult:
        body = {"serviceID": req.service_id, "mobileNumber": req.phone, "request-id": req.request_id}
        try:
            resp = await self._c.post(f"{self._base}/data", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        r = self._to_result(resp)
        if r.outcome is Outcome.SUCCESS and r.amount_charged is None:
            # Data responses carry the plan price in `amount` (no face value): that is our actual cost.
            r = replace(r, amount_charged=r.amount, amount=None)
        return r

    async def fetch_status(self, provider_reference: str) -> ProviderResult:
        try:
            resp = await self._c.post(f"{self._base}/transaction", json={"reference": provider_reference},
                                      headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        return self._to_result(resp)

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            resp = await self._c.get(f"{self._base}{path}", headers=self._h())
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(error=type(exc).__name__) from exc
        payload = _parse(resp.text) if resp.status_code < 500 else None
        if payload is None or str(payload.get("status", "")).lower() != "success":
            raise ProviderUnavailableError(status=resp.status_code)
        return payload

    async def balance(self) -> Money:
        funds = _money(((await self._get("/balance")).get("data") or {}).get("funds"))
        if funds is None:
            raise ProviderUnavailableError(error="bad_balance_response")
        return funds

    async def fetch_costs(self) -> list[CostEntry]:
        data = (await self._get("/services")).get("data")
        out: list[CostEntry] = []
        for row in (data.get("airtime") if isinstance(data, dict) else None) or []:
            try:
                pct = Decimal(str(row["discount"]))
                out.append(CostEntry("AIRTIME", str(row["network"]).upper().replace(" ", ""),
                                     str(row["serviceID"]), "DISCOUNT_BPS", int(pct * 100)))
            except (KeyError, InvalidOperation, ValueError):
                log.warning("inlomax_bad_airtime_cost_row")
        return out

    async def fetch_data_plans(self) -> list[DataPlanEntry]:
        """Accepts both documented shapes: data.dataPlans[] and a bare data[] list of plans."""
        data = (await self._get("/services")).get("data")
        rows = data.get("dataPlans") if isinstance(data, dict) else data
        out: list[DataPlanEntry] = []
        for row in rows if isinstance(rows, list) else []:
            try:
                cost = _money(row["amount"])
                if cost is None or not cost.is_positive():
                    raise ValueError("bad amount")
                out.append(DataPlanEntry(
                    str(row["serviceID"]), str(row["network"]).upper().replace(" ", ""), str(row["dataPlan"])[:40],
                    str(row.get("dataType", ""))[:40], str(row.get("validity", ""))[:40], cost.kobo))
            except (KeyError, TypeError, ValueError, AttributeError):
                log.warning("inlomax_bad_data_plan_row")
        return out

    # ---- electricity: UNVERIFIED against Inlomax's docs (field names follow their official PHP SDK) ----
    async def validate_meter(self, provider_disco_code: str, service_id: str, meter_number: str, meter_type: str) -> MeterInfo:
        body = {"meterNumber": meter_number, "disco": provider_disco_code}
        try:
            resp = await self._c.post(f"{self._base}{self._verify_path}", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(error=type(exc).__name__) from exc
        payload = _parse(resp.text) if resp.status_code < 500 else None
        if payload is None:
            raise ProviderUnavailableError(status=resp.status_code)
        status = str(payload.get("status", "")).lower()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if status == "failed":
            raise MeterInvalidError()
        name = _first(data, "customerName", "customer_name", "Customer_Name", "name")
        if status != "success" or not name:
            raise ProviderUnavailableError(status=resp.status_code, reason="unrecognised validation response")
        return MeterInfo(name[:120], _first(data, "address", "customerAddress", "Address")[:200], meter_number,
                         _money(data.get("minimumAmount") or data.get("minAmount")))

    async def purchase_electricity(self, req: ElectricityRequest) -> ProviderResult:
        if req.amount.kobo % 100:
            raise ValueError("electricity amount must be whole naira")
        body = {"serviceID": req.service_id, "amount": req.amount.kobo // 100, "meterNumber": req.meter_number,
                "request-id": req.request_id}
        try:
            resp = await self._c.post(f"{self._base}{self._elec_path}", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        return self._to_result(resp)

    async def fetch_electricity(self) -> list[ElectricityEntry]:
        data = (await self._get("/services")).get("data")
        out: list[ElectricityEntry] = []
        for row in (data.get("electricity") if isinstance(data, dict) else None) or []:
            try:
                name = _first(row, "disco", "name", "network", "provider")
                low = name.lower()
                mtype = (_first(row, "type", "meterType") or ("postpaid" if "postpaid" in low else "prepaid" if "prepaid" in low else "")).upper()
                if mtype not in ("PREPAID", "POSTPAID") or not name:
                    raise ValueError("cannot tell meter type")
                words = [w for w in re.split(r"[^a-z0-9]+", low) if w and w not in _NOISE_WORDS]
                code = words[0].upper() if words else ""
                out.append(ElectricityEntry(code, name[:80], code.lower(), mtype, str(row["serviceID"]),
                                            int(Decimal(str(row.get("discount", "0"))) * 100)))
            except (KeyError, ValueError, InvalidOperation, IndexError, AttributeError, TypeError):
                log.warning("inlomax_bad_electricity_row")
        return [e for e in out if e.disco_code]

    async def validate_smartcard(self, operator_service_id: str, smartcard_number: str) -> TVCustomerInfo:
        # Inlomax documents validatecable with serviceID + iucNum. The operator service ID
        # is stored separately from the selected bouquet's service ID.
        try:
            resp = await self._c.post(f"{self._base}/validatecable",
                json={"serviceID": operator_service_id, "iucNum": smartcard_number}, headers=self._h())
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(error=type(exc).__name__) from exc
        payload = _parse(resp.text) if resp.status_code < 500 else None
        if payload is None:
            raise ProviderUnavailableError(status=resp.status_code)
        status = str(payload.get("status", "")).lower()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if status == "failed":
            raise SmartcardInvalidError()
        name = _first(data, "customerName", "customer_name", "name")
        if status != "success" or not name:
            raise ProviderUnavailableError(status=resp.status_code, reason="unrecognised cable validation response")
        return TVCustomerInfo(name[:120], smartcard_number, _first(data, "currentBouquet", "current_bouquet")[:80])

    async def purchase_tv(self, req: TVRequest) -> ProviderResult:
        # A purchase is never retried here. Inlomax request-id de-duplication is undocumented.
        body = {"serviceID": req.service_id, "iucNum": req.smartcard_number, "request-id": req.request_id}
        try:
            resp = await self._c.post(f"{self._base}/subcable", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        r = self._to_result(resp)
        if r.outcome is Outcome.SUCCESS and r.amount_charged is None:
            r = replace(r, amount_charged=r.amount)
        return r

    async def fetch_tv_plans(self) -> list[TVPlanEntry]:
        data = (await self._get("/services")).get("data")
        rows = data.get("cablePlans") if isinstance(data, dict) else None
        out: list[TVPlanEntry] = []
        for row in rows if isinstance(rows, list) else []:
            try:
                amount = _money(row.get("amount"))
                sid = str(row["serviceID"]).strip()
                operator = _first(row, "cable", "operator", "network").upper().replace(" ", "")
                name = _first(row, "cablePlan", "plan", "name")
                discount = Decimal(str(row.get("discount", "0")))
                discount_bps = int(discount * 100)
                if not sid or not operator or not name or amount is None or amount.kobo <= 0 or not 0 <= discount_bps <= 2000:
                    raise ValueError("invalid TV plan")
                out.append(TVPlanEntry(sid, operator, operator.title(), name[:80], amount.kobo, discount_bps))
            except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
                log.warning("inlomax_bad_tv_plan_row")
        return out

    async def purchase_education(self, req: EducationRequest) -> ProviderResult:
        body = {"serviceID": req.service_id, "quantity": req.quantity, "request-id": req.request_id}
        try:
            resp = await self._c.post(f"{self._base}/education", json=body, headers=self._h())
        except httpx.HTTPError as exc:
            return ProviderResult(Outcome.UNKNOWN, message=type(exc).__name__)
        r = self._to_result(resp, log_shape=True)  # logs response structure only, never PIN values
        if r.outcome is Outcome.SUCCESS and r.amount_charged is None:
            r = replace(r, amount_charged=r.amount, amount=None)   # `amount` is what we were charged (see docs/providers-inlomax.md)
        return r
