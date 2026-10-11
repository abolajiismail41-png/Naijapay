"""Scripted stand-in provider for local development and tests (refused in production)."""
from collections import deque
from decimal import Decimal

from app.core.money import Money
from app.modules.providers.base import (
    AirtimeRequest, CostEntry, DataPlanEntry, DataRequest, EducationRequest, ElectricityEntry, ElectricityRequest,
    MeterInfo, Outcome, ProviderResult, TVCustomerInfo, TVPlanEntry, TVRequest,
)
from app.modules.providers.errors import MeterInvalidError, ProviderUnavailableError, SmartcardInvalidError

DEFAULT_COSTS = {"MTN": ("1", 250), "AIRTEL": ("2", 200), "GLO": ("3", 400), "9MOBILE": ("4", 300)}
DEFAULT_PLANS = [
    DataPlanEntry("100", "MTN", "1GB", "SME", "30 Days", 53_000),
    DataPlanEntry("101", "MTN", "2GB", "SME", "30 Days", 106_000),
    DataPlanEntry("200", "GLO", "1GB", "GIFTING", "30 Days", 45_000),
    DataPlanEntry("300", "AIRTEL", "1.5GB", "GIFTING", "30 Days", 100_000),
]
DEFAULT_DISCOS = [
    ElectricityEntry("IKEJA", "Ikeja Electric (IKEDC)", "ikeja", "PREPAID", "ik-pre", 50),
    ElectricityEntry("IKEJA", "Ikeja Electric (IKEDC)", "ikeja", "POSTPAID", "ik-post", 50),
    ElectricityEntry("ABUJA", "Abuja Electric (AEDC)", "abuja", "PREPAID", "ab-pre", 120),
]


class SandboxBillProvider:
    code = "inlomax-sandbox"
    can_query_by_request_id = False

    def __init__(self) -> None:
        self.script: deque[str] = deque()   # success | failed | processing | timeout | timeout_after_accept | no_token
        self.calls: list[AirtimeRequest | DataRequest | ElectricityRequest | EducationRequest | TVRequest] = []
        self.validate_calls: list[str] = []
        self.status_of: dict[str, Outcome] = {}
        self.charged: dict[str, Money] = {}
        self.tokens: dict[str, str] = {}
        self.pins: dict[str, tuple[tuple[str, str], ...]] = {}
        self.education_costs: dict[str, int] = {"1": 517_000, "2": 220_000}
        self.plans: list[DataPlanEntry] = list(DEFAULT_PLANS)
        self.discos: list[ElectricityEntry] = list(DEFAULT_DISCOS)
        self.cost_override: Money | None = None
        self.fail_status = False
        self.fail_validate = False
        self.float = Money.from_naira(1_000_000)

    def queue(self, *kinds: str) -> None:
        self.script.extend(kinds)

    def set_status(self, reference: str, outcome: Outcome) -> None:
        self.status_of[reference] = outcome

    def _run(self, req: AirtimeRequest | DataRequest | ElectricityRequest | EducationRequest | TVRequest, cost: Money,
             amount: Money | None, token: str | None = None,
             pins: tuple[tuple[str, str], ...] | None = None) -> ProviderResult:
        self.calls.append(req)
        kind = self.script.popleft() if self.script else "success"
        ref = f"sbx_{len(self.calls)}"
        charged = self.cost_override or cost
        if kind == "timeout":
            return ProviderResult(Outcome.UNKNOWN, message="ReadTimeout")
        if kind == "timeout_after_accept":
            self.status_of[ref], self.charged[ref] = Outcome.SUCCESS, charged
            return ProviderResult(Outcome.UNKNOWN, message="ReadTimeout")  # delivered, but we never heard
        if kind == "failed":
            return ProviderResult(Outcome.FAILED, message="Insufficient provider float")
        if kind == "processing":
            self.status_of[ref], self.charged[ref] = Outcome.PROCESSING, charged
            return ProviderResult(Outcome.PROCESSING, ref, amount, None)
        self.status_of[ref], self.charged[ref] = Outcome.SUCCESS, charged
        if kind in ("no_token", "no_pins"):
            return ProviderResult(Outcome.SUCCESS, ref, amount, charged)       # delivered, secret not returned
        if pins:
            pins = pins[:1] if kind == "partial" else pins
            self.pins[ref] = pins
        if token:
            self.tokens[ref] = token
        return ProviderResult(Outcome.SUCCESS, ref, amount, charged, token=token, units="31.2", pins=pins)

    async def purchase_airtime(self, req: AirtimeRequest) -> ProviderResult:
        return self._run(req, req.amount - req.amount.percent(Decimal("2.5")), req.amount)

    async def purchase_data(self, req: DataRequest) -> ProviderResult:
        plan = next(p for p in self.plans if p.provider_service_id == req.service_id)
        return self._run(req, Money(plan.cost_kobo), None)

    async def validate_meter(self, provider_disco_code: str, service_id: str, meter_number: str, meter_type: str) -> MeterInfo:
        self.validate_calls.append(meter_number)
        if self.fail_validate:
            raise ProviderUnavailableError()
        if meter_number.endswith("0000"):
            raise MeterInvalidError()
        return MeterInfo("TEST METER", "1 Test Street, Ikeja", meter_number, None)

    async def purchase_electricity(self, req: ElectricityRequest) -> ProviderResult:
        bps = next((d.discount_bps for d in self.discos if d.service_id == req.service_id), 0)
        token = None if req.meter_type == "POSTPAID" else f"{int(req.request_id[4:20], 16) % 10**20:020d}"
        return self._run(req, req.amount - req.amount.percent(Decimal(bps) / 100), req.amount, token)

    async def validate_smartcard(self, operator_service_id: str, smartcard_number: str) -> TVCustomerInfo:
        if not smartcard_number.isdigit() or len(smartcard_number) < 8:
            raise SmartcardInvalidError()
        return TVCustomerInfo("SANDBOX CUSTOMER", smartcard_number, "Sandbox Bouquet")

    async def purchase_tv(self, req: TVRequest) -> ProviderResult:
        plans = await self.fetch_tv_plans()
        plan = next((p for p in plans if p.provider_service_id == req.service_id), None)
        cost = Money(plan.cost_kobo) if plan else Money(100_000)
        return self._run(req, cost, None)

    async def fetch_tv_plans(self) -> list[TVPlanEntry]:
        return [TVPlanEntry("sandbox-gotv-jolli", "GOTV", "GOtv", "GOtv Jolli", 580_000, 0),
                TVPlanEntry("sandbox-dstv-padi", "DSTV", "DStv", "DStv Padi", 440_000, 0),
                TVPlanEntry("sandbox-startimes-basic", "STARTIMES", "StarTimes", "StarTimes Basic", 370_000, 0)]

    async def purchase_education(self, req: EducationRequest) -> ProviderResult:
        unit = self.education_costs[req.service_id]
        pins = tuple((f"{int(req.request_id[4:16], 16) % 10**10 + i:010d}", f"SRN{req.request_id[4:10].upper()}{i}")
                     for i in range(req.quantity))
        return self._run(req, Money(unit).times(req.quantity), None, None, pins)

    async def fetch_status(self, provider_reference: str) -> ProviderResult:
        if self.fail_status:
            return ProviderResult(Outcome.UNKNOWN, message="status_endpoint_down")
        o = self.status_of.get(provider_reference, Outcome.UNKNOWN)
        ok = o is Outcome.SUCCESS
        return ProviderResult(o, provider_reference, None, self.charged.get(provider_reference) if ok else None,
                              token=self.tokens.get(provider_reference) if ok else None,
                              pins=self.pins.get(provider_reference) if ok else None)

    async def balance(self) -> Money:
        if self.fail_status:
            raise ProviderUnavailableError()
        return self.float

    async def fetch_costs(self) -> list[CostEntry]:
        return [CostEntry("AIRTIME", n, sid, "DISCOUNT_BPS", bps) for n, (sid, bps) in DEFAULT_COSTS.items()]

    async def fetch_data_plans(self) -> list[DataPlanEntry]:
        return list(self.plans)

    async def fetch_electricity(self) -> list[ElectricityEntry]:
        return list(self.discos)
