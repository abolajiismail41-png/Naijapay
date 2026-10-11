from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.money import Money


class Outcome(StrEnum):
    SUCCESS = "SUCCESS"        # provider confirmed delivery
    FAILED = "FAILED"          # provider definitively refused: safe to refund
    PROCESSING = "PROCESSING"  # accepted, final result pending
    UNKNOWN = "UNKNOWN"        # timeout / 5xx / unparseable: delivery may or may not have happened


@dataclass(frozen=True)
class AirtimeRequest:
    request_id: str       # our transaction reference, sent as the provider's request-id
    service_id: str
    network: str
    phone: str            # local format, e.g. 08031234567
    amount: Money


@dataclass(frozen=True)
class DataRequest:
    request_id: str
    service_id: str   # the provider's plan id
    network: str
    phone: str        # local format


@dataclass(frozen=True)
class DataPlanEntry:
    provider_service_id: str
    network: str
    name: str         # e.g. 1GB
    data_type: str    # e.g. SME, GIFTING
    validity: str
    cost_kobo: int    # what the provider charges us


@dataclass(frozen=True)
class ElectricityRequest:
    request_id: str
    service_id: str          # provider service id for this disco + meter type
    provider_disco_code: str
    meter_type: str          # PREPAID | POSTPAID
    meter_number: str
    amount: Money


@dataclass(frozen=True)
class EducationRequest:
    request_id: str
    service_id: str
    quantity: int


@dataclass(frozen=True)
class TVRequest:
    request_id: str
    service_id: str          # provider bouquet/package service ID
    smartcard_number: str


@dataclass(frozen=True)
class TVPlanEntry:
    provider_service_id: str
    operator_code: str
    operator_name: str
    plan_name: str
    cost_kobo: int
    discount_bps: int = 0


@dataclass(frozen=True)
class TVCustomerInfo:
    customer_name: str
    smartcard_number: str
    current_bouquet: str = ""


@dataclass(frozen=True)
class MeterInfo:
    customer_name: str
    address: str
    meter_number: str
    min_amount: Money | None = None


@dataclass(frozen=True)
class ElectricityEntry:
    disco_code: str
    name: str
    provider_disco_code: str
    meter_type: str
    service_id: str
    discount_bps: int


@dataclass(frozen=True)
class ProviderResult:
    outcome: Outcome
    provider_reference: str | None = None
    amount: Money | None = None
    amount_charged: Money | None = None   # what the provider actually debited from our float
    message: str = ""
    http_status: int | None = None
    token: str | None = None   # electricity token / pin: a secret, never logged
    units: str | None = None
    pins: tuple[tuple[str, str], ...] | None = None   # exam pins as (pin, serial): secrets, never logged


@dataclass(frozen=True)
class CostEntry:
    category: str
    scope_key: str
    provider_service_id: str
    kind: str     # DISCOUNT_BPS | FIXED_KOBO
    value: int


class BillProvider(Protocol):
    code: str
    can_query_by_request_id: bool

    async def purchase_airtime(self, req: AirtimeRequest) -> ProviderResult: ...
    async def purchase_data(self, req: DataRequest) -> ProviderResult: ...
    async def purchase_education(self, req: EducationRequest) -> ProviderResult: ...
    async def validate_smartcard(self, operator_service_id: str, smartcard_number: str) -> TVCustomerInfo: ...
    async def purchase_tv(self, req: TVRequest) -> ProviderResult: ...
    async def fetch_tv_plans(self) -> list[TVPlanEntry]: ...
    async def validate_meter(self, provider_disco_code: str, service_id: str, meter_number: str, meter_type: str) -> MeterInfo: ...
    async def purchase_electricity(self, req: ElectricityRequest) -> ProviderResult: ...
    async def fetch_status(self, provider_reference: str) -> ProviderResult: ...
    async def balance(self) -> Money: ...
    async def fetch_costs(self) -> list[CostEntry]: ...
    async def fetch_data_plans(self) -> list[DataPlanEntry]: ...
    async def fetch_electricity(self) -> list[ElectricityEntry]: ...
