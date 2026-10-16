from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.asyncio import Redis
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
# NOTE: assumes decrypt(key, token, aad) mirrors encrypt(key, plaintext, aad).
from app.core.crypto import decrypt, encrypt
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.core.ids import uuid7
from app.core.money import Money
from app.core.ratelimit import hit
from app.modules.audit import service as audit
from app.modules.auth.deps import (
    PinStepUp,
    Principal,
    current_principal,
    require_permission,
    require_pin_step_up,
)
from app.modules.auth.rbac import Permission, has_permission
from app.modules.ledger.interface import SystemAccount
from app.modules.providers.base import Outcome, ProviderResult
from app.modules.services.models import PricingSnapshot
from app.modules.transactions.execution import TransactionService
from app.modules.transactions.models import Transaction
from app.modules.transactions.state import TxnStatus, transition
from app.modules.virtual_numbers.models import (
    VirtualNumberOrder,
    VirtualNumberPricing,
)
from app.modules.virtual_numbers.provider import (
    SMSManError,
    SMSManProvider,
    provider_cost_to_kobo,
)
from app.modules.wallet.models import Wallet
from app.modules.wallet.service import WalletService


router = APIRouter(
    prefix="/api/v1/virtual-numbers",
    tags=["virtual-numbers"],
)

admin_router = APIRouter(
    prefix="/api/v1/admin/virtual-numbers",
    tags=["admin-virtual-numbers"],
)

IdemKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9_\-:.]+$",
    ),
]

COUNTRIES_CACHE_KEY = "vnumber:smsman:countries:v1"
SERVICES_CACHE_KEY = "vnumber:smsman:services:v1"

COUNTRIES_CACHE_TTL = 3600
SERVICES_CACHE_TTL = 3600

PRICES_CACHE_TTL = 30
ADMIN_PRICES_CACHE_TTL = 300

# Price cache keys are v2: provider.prices() now returns the normalized
# {country: {application: quote}} shape, so entries cached by older code
# (v1) must not be read back.
PRICES_CACHE_KEY = "vnumber:smsman:prices:v2:{country_id}"
ADMIN_PRICES_CACHE_KEY = "vnumber:smsman:prices:admin:v2:{country_id}"

UNRESOLVED_ORDER_STATUSES = (
    "PENDING",
    "PROCESSING",
    "UNKNOWN",
    "CANCELLING",
)

FULFILLED_ORDER_STATUSES = {
    "ACTIVE",
    "SMS_RECEIVED",
    "CANCELLED",
}

# Statuses after which nothing more will happen to the order. Clients use
# ``is_final`` to decide when it is safe to stop polling / navigate.
FINAL_ORDER_STATUSES = {
    "SMS_RECEIVED",
    "CANCELLED",
    "FAILED",
    "EXPIRED",
}

# A number can be cancelled only after this long without a code.
CANCEL_AFTER_SECONDS = 120

# The provider's own activation window; used only when the order row does
# not carry an explicit expiry.
ACTIVATION_WINDOW_SECONDS = 20 * 60

# The customer polls this endpoint every few seconds while waiting.
SMS_REFRESH_LIMIT_PER_HOUR = 900


class VirtualNumberError(AppError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "virtual_number_error",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.context = (
            {"details": details}
            if details is not None
            else {}
        )


class PurchaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_id: int = Field(strict=True, ge=0)
    # SMS-Man requires application_id >= 1. Allowing 0 here used to fail
    # AFTER funds were held and the transaction was moved to PROCESSING.
    application_id: int = Field(strict=True, ge=1)
    confirmed_price_kobo: int = Field(strict=True, gt=0)


class PricingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markup_percent: Decimal = Field(ge=0, le=500)
    fixed_fee_kobo: int = Field(ge=0, le=100_000_000)
    min_price_kobo: int = Field(gt=0, le=500_000_000)
    max_price_kobo: int = Field(gt=0, le=500_000_000)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_price_bounds(self) -> "PricingPatch":
        if self.min_price_kobo > self.max_price_kobo:
            raise ValueError(
                "Minimum price cannot exceed maximum price."
            )
        return self


class ManualResolutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(pattern=r"^(SUCCESS|FAILED)$")
    note: str = Field(min_length=8, max_length=200)

    provider_request_id: int | None = Field(
        default=None,
        gt=0,
    )

    phone_number: str | None = Field(
        default=None,
        min_length=5,
        max_length=40,
        pattern=r"^[+0-9 ()-]+$",
    )

    provider_cost_kobo: int | None = Field(
        default=None,
        gt=0,
    )


# ---------------------------------------------------------------------
# PROVIDER AND COMMON HELPERS
# ---------------------------------------------------------------------


def _provider(
    request: Request,
    settings: Settings,
) -> SMSManProvider:
    return SMSManProvider(
        request.app.state.http,
        settings.smsman_api_key,
        settings.smsman_base_url,
    )


def _enabled(settings: Settings) -> None:
    if not settings.smsman_enabled:
        raise VirtualNumberError(
            "Virtual Numbers is temporarily unavailable.",
            status_code=503,
            code="virtual_numbers_disabled",
        )


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default

    try:
        if isinstance(value, float) and not value.is_integer():
            return default

        return int(value)

    except (TypeError, ValueError, OverflowError):
        return default


def _positive_id(value: Any) -> int | None:
    """Parse a non-negative integer ID without accepting booleans/fractions."""
    if isinstance(value, bool) or value is None:
        return None

    if isinstance(value, float) and not value.is_integer():
        return None

    if isinstance(value, Decimal):
        if (
            not value.is_finite()
            or value != value.to_integral_value()
        ):
            return None

    try:
        text_value = str(value).strip()

        if not text_value:
            return None

        parsed = int(text_value)

    except (TypeError, ValueError, OverflowError):
        return None

    return parsed if parsed >= 0 else None


def _mapping_get(
    mapping: Any,
    key: int | str,
) -> Any:
    """Read provider mappings with integer or string keys."""
    if not isinstance(mapping, dict):
        return None

    value = mapping.get(str(key))

    if value is not None:
        return value

    return mapping.get(key)


def _catalogue_country(
    countries: list[dict[str, Any]],
    country_id: int,
) -> dict[str, Any] | None:
    for item in countries:
        if _safe_int(item.get("id"), -1) == country_id:
            return item

    return None


def _catalogue_service(
    services: list[dict[str, Any]],
    application_id: int,
) -> dict[str, Any] | None:
    for item in services:
        if _safe_int(item.get("id"), -1) == application_id:
            return item

    return None


def _price_index(
    raw: Any,
    country_id: int,
) -> dict[int, dict[str, Any]]:
    """
    Index SMS-Man quotes by application ID.

    ``raw`` is the output of ``SMSManProvider.prices(country_id)``, which is
    always normalized to ``{country_id: {application_id: quote}}``. The
    provider adapter absorbs the documented-vs-live response shape
    difference, so no shape guessing happens here. (The old multi-format
    guessing mistook an application keyed "5" for country 5.)

    A quote explicitly assigned to another country is rejected.
    """
    indexed: dict[int, dict[str, Any]] = {}

    country_data = _mapping_get(raw, country_id)

    if not isinstance(country_data, dict):
        return indexed

    for application_key, quote in country_data.items():
        if (
            not isinstance(quote, dict)
            or quote.get("cost") is None
        ):
            continue

        quote_country = _positive_id(quote.get("country_id"))

        if (
            quote_country is not None
            and quote_country != country_id
        ):
            continue

        application_id = _positive_id(
            quote.get("application_id", application_key)
        )

        if application_id is not None:
            indexed[application_id] = quote

    return indexed


def _effective_pricing(
    settings: Settings,
    pricing_row: VirtualNumberPricing | None,
) -> dict[str, Any]:
    """
    Return the active pricing configuration.

    Database pricing takes precedence over environment defaults.
    """
    return {
        "markup_percent": (
            pricing_row.markup_percent
            if pricing_row is not None
            else settings.smsman_markup_percent
        ),
        "fixed_fee_kobo": (
            pricing_row.fixed_fee_kobo
            if pricing_row is not None
            else settings.smsman_fixed_fee_kobo
        ),
        "min_price_kobo": (
            pricing_row.min_price_kobo
            if pricing_row is not None
            else settings.smsman_min_price_kobo
        ),
        "max_price_kobo": (
            pricing_row.max_price_kobo
            if pricing_row is not None
            else settings.smsman_max_price_kobo
        ),
        "enabled": (
            pricing_row.enabled
            if pricing_row is not None
            else True
        ),
    }


def _price_payload(
    raw: Any,
    country_id: int,
    application_id: int,
    settings: Settings,
    pricing_row: VirtualNumberPricing | None = None,
    *,
    price_index: dict[int, dict[str, Any]] | None = None,
    reject: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Convert a provider quote into a customer-facing NGN price.

    Formula:
        selling price = provider cost + percentage markup + fixed fee

    For a fixed ₦1,000 profit:
        markup_percent = 0
        fixed_fee_kobo = 100000

    Price ceilings are independent of profit settings. This function does
    not implement a separate maximum-profit cap.
    """

    def no(reason: str) -> None:
        if reject is not None:
            reject.append(reason)

        return None

    pricing = _effective_pricing(settings, pricing_row)

    if not pricing["enabled"]:
        return no("pricing_disabled")

    index = (
        price_index
        if price_index is not None
        else _price_index(raw, country_id)
    )

    item = index.get(application_id)

    if (
        not isinstance(item, dict)
        or item.get("cost") is None
    ):
        return no("no_quote_for_service")

    try:
        provider_cost_kobo = provider_cost_to_kobo(
            item["cost"],
            settings.smsman_ngn_per_unit,
        )

        markup_percent = Decimal(
            str(pricing["markup_percent"])
        )
        fixed_fee_kobo = int(pricing["fixed_fee_kobo"])
        min_price_kobo = int(pricing["min_price_kobo"])
        max_price_kobo = int(pricing["max_price_kobo"])

        if not markup_percent.is_finite() or markup_percent < 0:
            return no("invalid_markup")

        if provider_cost_kobo <= 0:
            return no("non_positive_cost")

        if fixed_fee_kobo < 0:
            return no("invalid_fixed_fee")

        if min_price_kobo <= 0 or max_price_kobo <= 0:
            return no("invalid_price_bounds")

        if min_price_kobo > max_price_kobo:
            return no("invalid_price_bounds")

        multiplier = (
            Decimal("1")
            + markup_percent / Decimal("100")
        )

        percentage_price = (
            Decimal(provider_cost_kobo) * multiplier
        ).quantize(
            Decimal("1"),
            rounding=ROUND_CEILING,
        )

        price_kobo = int(percentage_price) + fixed_fee_kobo

        raw_count = item.get("count")

        if raw_count is None:
            inventory: int | None = None
        else:
            parsed_count = _safe_int(raw_count, -1)

            inventory = (
                max(0, parsed_count)
                if parsed_count >= 0
                else None
            )

    except SMSManError as exc:
        return no(f"conversion:{exc.code}")

    except (ValueError, TypeError, ArithmeticError) as exc:
        return no(f"calc:{type(exc).__name__}")

    if price_kobo <= 0:
        return no("non_positive_price")

    if price_kobo < min_price_kobo:
        return no("below_min_price")

    if price_kobo > max_price_kobo:
        return no("above_max_price")

    profit_kobo = price_kobo - provider_cost_kobo

    return {
        "provider_cost_kobo": provider_cost_kobo,
        "price_kobo": price_kobo,
        "price": Money(price_kobo).naira_str(),
        "profit_kobo": profit_kobo,
        "inventory": inventory,
        "available": (
            inventory > 0
            if inventory is not None
            else None
        ),
        "currency": "NGN",
    }


async def _cached_json(
    redis: Redis,
    key: str,
    ttl_seconds: int,
    fetch: Callable[[], Awaitable[Any]],
) -> Any:
    """
    Read/write JSON through Redis when possible.

    Redis cache failures fall back to the provider rather than disabling
    the integration.
    """
    try:
        cached = await redis.get(key)

        if cached is not None:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")

            if isinstance(cached, str):
                return json.loads(cached)

    except Exception:
        pass

    value = await fetch()

    try:
        encoded = json.dumps(
            value,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        await redis.set(
            key,
            encoded,
            ex=ttl_seconds,
        )

    except Exception:
        pass

    return value


async def _cached_catalogues(
    provider: SMSManProvider,
    redis: Redis,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    countries_value, services_value = await asyncio.gather(
        _cached_json(
            redis,
            COUNTRIES_CACHE_KEY,
            COUNTRIES_CACHE_TTL,
            provider.countries,
        ),
        _cached_json(
            redis,
            SERVICES_CACHE_KEY,
            SERVICES_CACHE_TTL,
            provider.services,
        ),
    )

    if not isinstance(countries_value, list):
        raise SMSManError(
            "Invalid country catalogue response."
        )

    if not isinstance(services_value, list):
        raise SMSManError(
            "Invalid service catalogue response."
        )

    return countries_value, services_value


async def _cached_prices(
    provider: SMSManProvider,
    redis: Redis,
    country_id: int,
    *,
    admin: bool = False,
) -> Any:
    if admin:
        key = ADMIN_PRICES_CACHE_KEY.format(country_id=country_id)
        ttl = ADMIN_PRICES_CACHE_TTL
    else:
        key = PRICES_CACHE_KEY.format(country_id=country_id)
        ttl = PRICES_CACHE_TTL

    return await _cached_json(
        redis,
        key,
        ttl,
        lambda: provider.prices(country_id),
    )


async def _catalogues(
    provider: SMSManProvider,
    redis: Redis,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return await _cached_catalogues(provider, redis)


def _country_view(
    values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": _safe_int(item.get("id"), -1),
            "name": str(item.get("title", "")),
        }
        for item in values
        if (
            _safe_int(item.get("id"), -1) >= 0
            and item.get("title")
        )
    ]


def _service_view(
    values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": _safe_int(item.get("id"), -1),
            "name": str(item.get("name", "")),
            "code": item.get("code"),
        }
        for item in values
        if (
            _safe_int(item.get("id"), -1) >= 0
            and item.get("name")
        )
    ]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value


def _assigned_at(order: VirtualNumberOrder) -> datetime | None:
    """When the provider assigned the number (falls back to created_at)."""
    explicit = getattr(order, "assigned_at", None)

    return _as_utc(explicit) or _as_utc(order.created_at)


def _expires_at(order: VirtualNumberOrder) -> datetime | None:
    explicit = _as_utc(getattr(order, "expires_at", None))

    if explicit is not None:
        return explicit

    start = _assigned_at(order)

    if start is None or order.provider_request_id is None:
        return None

    return start + timedelta(seconds=ACTIVATION_WINDOW_SECONDS)


def _cancel_available_at(order: VirtualNumberOrder) -> datetime | None:
    start = _assigned_at(order)

    if start is None:
        return None

    return start + timedelta(seconds=CANCEL_AFTER_SECONDS)


def _decrypt_code(
    order: VirtualNumberOrder,
    settings: Settings,
) -> str | None:
    if not order.sms_code:
        return None

    try:
        return decrypt(
            settings.encryption_key.get_secret_value(),
            order.sms_code,
            f"virtual-number:{order.id}",
        )

    except Exception:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _view(
    txn: Transaction,
    order: VirtualNumberOrder,
    sms_code: str | None = None,
) -> dict[str, Any]:
    price_kobo = int(order.selling_price_kobo)
    has_number = order.provider_request_id is not None

    return {
        "id": str(order.id),
        # Alias so clients can read the order id from a purchase response.
        "order_id": str(order.id),
        "reference": txn.reference,
        "service_type": "VNUMBER",
        "status": order.status,
        "transaction_status": txn.status,
        "is_final": order.status in FINAL_ORDER_STATUSES,
        "country_id": order.country_id,
        "country_name": order.country_name,
        "application_id": order.application_id,
        "service_name": order.service_name,
        "phone_number": order.phone_number,
        "price_kobo": price_kobo,
        "price": Money(price_kobo).naira_str(),
        "currency": "NGN",
        "sms_code": sms_code,
        "failure_reason": order.failure_reason,
        "refund_status": (
            "REFUNDED"
            if txn.refund_journal_reference
            else (
                "NOT_ISSUED"
                if order.status == "CANCELLED"
                else None
            )
        ),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "assigned_at": _iso(_assigned_at(order)) if has_number else None,
        "expires_at": _iso(_expires_at(order)) if has_number else None,
        "cancel_available_at": (
            _iso(_cancel_available_at(order)) if has_number else None
        ),
    }


async def _fresh_view(
    db: AsyncSession,
    txn: Transaction,
    order: VirtualNumberOrder,
    sms_code: str | None = None,
) -> dict[str, Any]:
    """
    Build the response view after reloading both rows.

    Use this wherever a view is built right after an UPDATE. It guarantees
    no expired attribute is lazy-loaded inside the synchronous ``_view``,
    which would raise MissingGreenlet in an async session. (The models also
    set eager_defaults=True; this is a second line of defence for any
    server-generated column added later.)
    """
    await db.refresh(order)
    await db.refresh(txn)

    return _view(txn, order, sms_code)


async def _get_order_and_transaction(
    db: AsyncSession,
    order_id: uuid.UUID,
    user_id: Any,
) -> tuple[VirtualNumberOrder, Transaction]:
    result = await db.execute(
        select(
            VirtualNumberOrder,
            Transaction,
        )
        .join(
            Transaction,
            Transaction.id == VirtualNumberOrder.transaction_id,
        )
        .where(
            VirtualNumberOrder.id == order_id,
            VirtualNumberOrder.user_id == user_id,
        )
    )

    row = result.first()

    if row is None:
        raise NotFoundError(
            "Virtual number order not found."
        )

    return row[0], row[1]


# ---------------------------------------------------------------------
# CUSTOMER CATALOGUE
# ---------------------------------------------------------------------


@router.get("/countries")
async def countries(
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_app_settings),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    _enabled(settings)

    await hit(
        redis,
        f"rl:vnumber:catalogue:{principal.user.id}",
        60,
        3600,
    )

    try:
        provider = _provider(request, settings)
        values, _ = await _cached_catalogues(provider, redis)

        return ok(_country_view(values))

    except SMSManError as exc:
        raise VirtualNumberError(
            "Country catalogue is temporarily unavailable.",
            status_code=503,
            code="provider_unavailable",
        ) from exc


@router.get("/services")
async def services(
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_app_settings),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    _enabled(settings)

    await hit(
        redis,
        f"rl:vnumber:catalogue:{principal.user.id}",
        60,
        3600,
    )

    try:
        provider = _provider(request, settings)
        _, values = await _cached_catalogues(provider, redis)

        return ok(_service_view(values))

    except SMSManError as exc:
        raise VirtualNumberError(
            "Service catalogue is temporarily unavailable.",
            status_code=503,
            code="provider_unavailable",
        ) from exc


@router.get("/prices")
async def prices(
    country_id: Annotated[int, Query(ge=0)],
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_app_settings),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    _enabled(settings)

    await hit(
        redis,
        f"rl:vnumber:catalogue:{principal.user.id}",
        60,
        3600,
    )

    provider = _provider(request, settings)

    try:
        raw_prices, catalogues = await asyncio.gather(
            _cached_prices(
                provider,
                redis,
                country_id,
            ),
            _cached_catalogues(provider, redis),
        )

        country_values, service_values = catalogues
        pricing_row = await db.get(VirtualNumberPricing, 1)

    except SMSManError as exc:
        raise VirtualNumberError(
            "Prices are temporarily unavailable. Please try again.",
            status_code=503,
            code="provider_unavailable",
        ) from exc

    country = _catalogue_country(
        country_values,
        country_id,
    )

    if country is None:
        raise VirtualNumberError(
            "The selected country is not present in the provider catalogue.",
            status_code=404,
            code="country_not_found",
            details={"country_id": country_id},
        )

    country_name = str(country.get("title", ""))
    index = _price_index(raw_prices, country_id)

    output: list[dict[str, Any]] = []

    for service_item in service_values:
        service_id = _safe_int(
            service_item.get("id"),
            -1,
        )
        service_name = service_item.get("name")

        if service_id < 0 or not service_name:
            continue

        quote = _price_payload(
            raw_prices,
            country_id,
            service_id,
            settings,
            pricing_row,
            price_index=index,
        )

        if quote is None:
            continue

        output.append({
            "country_id": country_id,
            "country_name": country_name,
            "application_id": service_id,
            "service_name": str(service_name),
            "service_code": service_item.get("code"),
            **quote,
        })

    output.sort(
        key=lambda item: item["service_name"].casefold()
    )

    return ok(output)


# ---------------------------------------------------------------------
# CUSTOMER PURCHASE
# ---------------------------------------------------------------------


@router.post("/orders", status_code=202)
async def purchase(
    body: PurchaseIn,
    request: Request,
    key: IdemKey,
    step: PinStepUp = Depends(require_pin_step_up),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    _enabled(settings)

    user_id = step.principal.user.id

    await hit(
        redis,
        f"rl:vnumber:buy:{user_id}",
        5,
        3600,
    )

    request_hash = hashlib.sha256(
        f"vnumber:{body.country_id}:{body.application_id}".encode()
    ).hexdigest()

    idempotency_key = f"vnumber:{key}"

    async def existing_purchase() -> dict[str, Any] | None:
        existing_txn = (
            await db.execute(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

        if existing_txn is None:
            return None

        if existing_txn.request_hash != request_hash:
            raise ConflictError(
                "This idempotency key was used for a different purchase."
            )

        existing_order = (
            await db.execute(
                select(VirtualNumberOrder).where(
                    VirtualNumberOrder.transaction_id
                    == existing_txn.id
                )
            )
        ).scalar_one_or_none()

        if existing_order is None:
            raise ConflictError(
                "This purchase is being reconciled. Check its status shortly."
            )

        return ok(
            _view(
                existing_txn,
                existing_order,
                _decrypt_code(existing_order, settings),
            ),
            "Existing purchase request returned.",
        )

    previous = await existing_purchase()

    if previous is not None:
        return previous

    provider = _provider(request, settings)

    # Fetch a fresh provider price before reserving customer funds.
    try:
        raw_prices = await provider.prices(body.country_id)
        price_index = _price_index(
            raw_prices,
            body.country_id,
        )

        pricing_row = await db.get(
            VirtualNumberPricing,
            1,
        )

        reasons: list[str] = []

        quote = _price_payload(
            raw_prices,
            body.country_id,
            body.application_id,
            settings,
            pricing_row,
            price_index=price_index,
            reject=reasons,
        )

        if quote is None:
            raise VirtualNumberError(
                "Pricing is unavailable for this selection. Check the "
                "provider price response, application ID, NGN conversion "
                "rate, and enabled pricing rules.",
                status_code=409,
                code="price_unavailable",
                details={
                    "country_id": body.country_id,
                    "application_id": body.application_id,
                    "provider_price_records": len(price_index),
                    "reason": reasons[0] if reasons else None,
                },
            )

        if quote["available"] is not True:
            raise VirtualNumberError(
                "Inventory is unavailable or could not be confirmed. "
                "Refresh prices and try again.",
                status_code=409,
                code="inventory_unavailable",
            )

        if quote["price_kobo"] != body.confirmed_price_kobo:
            raise VirtualNumberError(
                "The price has changed. Review the new price before purchasing.",
                status_code=409,
                code="price_changed",
                details={
                    "price_kobo": quote["price_kobo"],
                    "price": quote["price"],
                },
            )

        country_values, service_values = await _catalogues(
            provider,
            redis,
        )

    except SMSManError as exc:
        raise VirtualNumberError(
            "Virtual Numbers is temporarily unavailable.",
            status_code=503,
            code="provider_unavailable",
        ) from exc

    country = _catalogue_country(
        country_values,
        body.country_id,
    )
    service = _catalogue_service(
        service_values,
        body.application_id,
    )

    if country is None or service is None:
        raise VirtualNumberError(
            "This selection is no longer available in the provider catalogue.",
            status_code=409,
            code="catalogue_changed",
        )

    country_name = str(country["title"])
    service_name = str(service["name"])

    raw_service_price = price_index.get(
        body.application_id
    )

    if (
        not isinstance(raw_service_price, dict)
        or raw_service_price.get("cost") is None
    ):
        raise VirtualNumberError(
            "Provider pricing changed. Please refresh and try again.",
            status_code=409,
            code="price_unavailable",
        )

    try:
        provider_price_decimal = Decimal(
            str(raw_service_price["cost"])
        )

        if (
            not provider_price_decimal.is_finite()
            or provider_price_decimal <= 0
        ):
            raise ValueError(
                "Invalid provider price."
            )

        # IMPORTANT:
        # This is in SMS-Man provider price units (settings.smsman_currency),
        # not NGN kobo. It is an integer ceiling on what SMS-Man may charge,
        # so for cheap services (cost < 1 unit) it is a loose cap. Verify
        # that get-prices quotes are in the same currency you send here.
        provider_max_price = int(
            provider_price_decimal.to_integral_value(
                rounding=ROUND_CEILING
            )
        )

        if provider_max_price <= 0:
            raise ValueError(
                "Invalid provider maxPrice."
            )

    except (ValueError, TypeError, ArithmeticError) as exc:
        raise VirtualNumberError(
            "The provider returned an invalid price.",
            status_code=503,
            code="provider_price_invalid",
        ) from exc

    wallet = await WalletService(db).get_or_create(user_id)

    # Serialize spending against this wallet.
    locked_wallet = (
        await db.execute(
            select(Wallet)
            .where(Wallet.id == wallet.id)
            .with_for_update()
        )
    ).scalar_one()

    _ = locked_wallet

    unresolved = (
        await db.execute(
            select(VirtualNumberOrder)
            .where(
                VirtualNumberOrder.user_id == user_id,
                VirtualNumberOrder.status.in_(
                    UNRESOLVED_ORDER_STATUSES
                ),
            )
            .with_for_update()
            .limit(1)
        )
    ).scalar_one_or_none()

    if unresolved is not None:
        raise ConflictError(
            "You have a virtual-number order awaiting provider confirmation."
        )

    transaction_id = uuid7()
    transaction_reference = f"txn_{uuid7().hex}"

    inserted_id = (
        await db.execute(
            insert(Transaction)
            .values(
                id=transaction_id,
                reference=transaction_reference,
                user_id=user_id,
                service_type="VNUMBER",
                status=TxnStatus.INITIATED.value,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                amount_kobo=quote["price_kobo"],
                price_kobo=quote["price_kobo"],
                provider_code="smsman",
                provider_service_id=str(body.application_id),
            )
            .on_conflict_do_nothing(
                constraint="uq_transactions_user_idempotency"
            )
            .returning(Transaction.id)
        )
    ).scalar_one_or_none()

    if inserted_id is None:
        await db.rollback()

        previous = await existing_purchase()

        if previous is not None:
            return previous

        raise ConflictError(
            "The purchase request could not be reserved. Retry using the "
            "same idempotency key."
        )

    txn = await db.get(
        Transaction,
        transaction_id,
    )

    if txn is None:
        await db.rollback()
        raise RuntimeError(
            "Transaction disappeared after insertion."
        )

    order = VirtualNumberOrder(
        id=uuid7(),
        transaction_id=transaction_id,
        user_id=user_id,
        country_id=body.country_id,
        country_name=country_name,
        application_id=body.application_id,
        service_name=service_name,
        status="PENDING",
        provider_cost_kobo=quote["provider_cost_kobo"],
        selling_price_kobo=quote["price_kobo"],
    )

    db.add(order)

    profit_kobo = (
        quote["price_kobo"]
        - quote["provider_cost_kobo"]
    )

    margin_pct = (
        Decimal(profit_kobo)
        * Decimal("100")
        / Decimal(quote["price_kobo"])
    )

    db.add(
        PricingSnapshot(
            transaction_id=transaction_id,
            rule_id=None,
            rule_version=None,
            method="MARKUP",
            provider_code="smsman",
            cost_source="SMSMAN",
            cost_kobo=quote["provider_cost_kobo"],
            markup_kobo=profit_kobo,
            fee_kobo=0,
            list_price_kobo=quote["price_kobo"],
            discount_kobo=0,
            customer_price_kobo=quote["price_kobo"],
            referral_commission_kobo=0,
            processing_cost_kobo=0,
            gross_profit_before_discount_kobo=profit_kobo,
            gross_profit_kobo=profit_kobo,
            net_contribution_kobo=profit_kobo,
            margin_pct=margin_pct,
            capped=False,
            subsidized=False,
        )
    )

    ttl = max(
        1,
        step.expires_at - int(datetime.now(UTC).timestamp()),
    )

    pin_consumed = await redis.set(
        f"pin:used:{step.jti}",
        "1",
        ex=ttl,
        nx=True,
    )

    if not pin_consumed:
        await db.rollback()

        raise ForbiddenError(
            "Please confirm with your transaction PIN again."
        )

    try:
        hold = await WalletService(db).debit(
            user_id,
            Money(quote["price_kobo"]),
            reference=f"hold:{transaction_reference}",
            kind="purchase.hold",
            destination=SystemAccount.PROVIDER_CLEARING,
            description="Virtual number purchase",
            meta={
                "transaction": transaction_reference,
                "service": "VNUMBER",
            },
        )

        txn.hold_journal_reference = hold.reference

        transition(
            db,
            txn,
            TxnStatus.PENDING,
            "virtual number funds held",
        )

        audit.record(
            db,
            action="transaction.created",
            actor_user_id=user_id,
            resource_type="transaction",
            resource_id=transaction_reference,
            meta={
                "service": "VNUMBER",
                "country_id": body.country_id,
                "application_id": body.application_id,
            },
        )

        await db.commit()

    except Exception:
        await db.rollback()
        raise

    txn_service = TransactionService(
        db,
        redis,
        settings,
        {},
    )

    # Commit PROCESSING before the external provider request.
    try:
        transition(
            db,
            txn,
            TxnStatus.PROCESSING,
            "requesting SMS-Man number",
        )

        await db.commit()

    except Exception:
        await db.rollback()
        raise

    try:
        result = await provider.purchase(
            body.country_id,
            body.application_id,
            provider_max_price,
            settings.smsman_currency,
        )

        request_id = int(result["request_id"])
        phone_number = str(result["number"])

        if request_id <= 0 or not phone_number:
            raise SMSManError(
                "Provider returned an invalid activation response.",
                uncertain=True,
                code="invalid_activation_response",
            )

        # Save provider evidence before settlement.
        order.provider_request_id = request_id
        order.phone_number = phone_number
        order.status = "ACTIVE"

        txn.provider_reference = str(request_id)

        await db.commit()

        txn = await txn_service.apply(
            txn.id,
            ProviderResult(
                Outcome.SUCCESS,
                provider_reference=str(request_id),
                amount_charged=Money(
                    quote["provider_cost_kobo"]
                ),
                message="SMS-Man confirmed number activation",
            ),
            source="smsman",
        )

        audit.record(
            db,
            action="virtual_number.purchased",
            actor_user_id=user_id,
            resource_type="virtual_number_order",
            resource_id=str(order.id),
            meta={
                "provider_request_id": request_id,
            },
        )

        await db.commit()

    except SMSManError as exc:
        order.provider_error_code = exc.code

        if exc.uncertain:
            order.status = "UNKNOWN"

            txn = await txn_service.apply(
                txn.id,
                ProviderResult(
                    Outcome.UNKNOWN,
                    message=(
                        "Provider purchase outcome is uncertain; "
                        "reconciliation is required."
                    ),
                ),
                source="smsman",
            )

        else:
            order.status = "FAILED"
            order.failure_reason = (
                "The provider could not fulfil this request."
            )

            txn = await txn_service.apply(
                txn.id,
                ProviderResult(
                    Outcome.FAILED,
                    message="SMS-Man rejected the number purchase",
                ),
                source="smsman",
            )

        await db.commit()

    except Exception:
        # The provider may have fulfilled the request. Preserve the
        # committed PROCESSING transaction for reconciliation.
        await db.rollback()
        raise

    return ok(
        await _fresh_view(db, txn, order),
        "Purchase submitted. Check the order status for updates.",
    )


# ---------------------------------------------------------------------
# CUSTOMER ORDERS
# ---------------------------------------------------------------------


@router.get("/orders")
async def my_orders(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                VirtualNumberOrder,
                Transaction,
            )
            .join(
                Transaction,
                Transaction.id == VirtualNumberOrder.transaction_id,
            )
            .where(
                VirtualNumberOrder.user_id == principal.user.id
            )
            .order_by(
                VirtualNumberOrder.created_at.desc()
            )
            .limit(100)
        )
    ).all()

    return ok([
        _view(txn, order, _decrypt_code(order, settings))
        for order, txn in rows
    ])


@router.get("/orders/{order_id}")
async def order_detail(
    order_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    order, txn = await _get_order_and_transaction(
        db,
        order_id,
        principal.user.id,
    )

    return ok(_view(txn, order, _decrypt_code(order, settings)))


@router.post("/orders/{order_id}/refresh")
@router.post("/orders/{order_id}/sms")
async def get_sms(
    order_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    _enabled(settings)

    # The customer page polls this every few seconds while a number is
    # waiting for its code.
    await hit(
        redis,
        f"rl:vnumber:sms:{principal.user.id}",
        SMS_REFRESH_LIMIT_PER_HOUR,
        3600,
    )

    order = (
        await db.execute(
            select(VirtualNumberOrder)
            .where(
                VirtualNumberOrder.id == order_id,
                VirtualNumberOrder.user_id == principal.user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if order is None:
        raise NotFoundError(
            "Virtual number order not found."
        )

    # A code that is already stored never needs another provider call.
    if order.status == "SMS_RECEIVED":
        stored = _decrypt_code(order, settings)

        if stored:
            return ok({
                "order_id": str(order.id),
                "status": "SMS_RECEIVED",
                "sms_code": stored,
                "is_final": True,
            })

    if (
        order.status not in {"ACTIVE", "SMS_RECEIVED"}
        or order.provider_request_id is None
    ):
        raise VirtualNumberError(
            "SMS retrieval is not available for this order.",
            status_code=409,
            code="activation_not_active",
        )

    try:
        data = await _provider(
            request,
            settings,
        ).sms(order.provider_request_id)

        # provider.sms() sets status to "received" or "waiting".
        code = data.get("sms_code")

        if (
            data.get("status") != "received"
            or not isinstance(code, str)
            or not code
        ):
            return ok({
                "order_id": str(order.id),
                "status": "WAITING",
                "sms_code": None,
                "is_final": False,
            })

        order.sms_code = encrypt(
            settings.encryption_key.get_secret_value(),
            code,
            f"virtual-number:{order.id}",
        )

        order.status = "SMS_RECEIVED"

        await db.commit()

        return ok({
            "order_id": str(order.id),
            "status": "SMS_RECEIVED",
            "sms_code": code,
            "is_final": True,
        })

    except SMSManError as exc:
        await db.rollback()

        raise VirtualNumberError(
            "SMS could not be retrieved right now.",
            status_code=503,
            code="sms_unavailable",
        ) from exc


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    _enabled(settings)

    await hit(
        redis,
        f"rl:vnumber:cancel:{principal.user.id}",
        10,
        3600,
    )

    order = (
        await db.execute(
            select(VirtualNumberOrder)
            .where(
                VirtualNumberOrder.id == order_id,
                VirtualNumberOrder.user_id == principal.user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if order is None:
        raise NotFoundError(
            "Virtual number order not found."
        )

    # Once a code has been delivered the order is final: no cancel.
    if (
        order.status != "ACTIVE"
        or order.provider_request_id is None
    ):
        raise VirtualNumberError(
            "This order cannot be cancelled in its current state.",
            status_code=409,
            code="cancellation_not_allowed",
        )

    opens_at = _cancel_available_at(order)

    if opens_at is not None and datetime.now(UTC) < opens_at:
        raise VirtualNumberError(
            "You can cancel after 2 minutes if no code arrives.",
            status_code=409,
            code="cancellation_too_early",
            details={"cancel_available_at": opens_at.isoformat()},
        )

    order.status = "CANCELLING"
    order.cancellation_requested_at = datetime.now(UTC)

    await db.commit()

    try:
        await _provider(
            request,
            settings,
        ).change_status(
            order.provider_request_id,
            "close",
        )

    except SMSManError as exc:
        await db.rollback()

        if not exc.uncertain:
            order = await db.get(
                VirtualNumberOrder,
                order_id,
            )

            if (
                order is not None
                and order.status == "CANCELLING"
            ):
                order.status = "ACTIVE"
                await db.commit()

        raise VirtualNumberError(
            "Cancellation has not been conclusively confirmed. "
            "No refund was issued.",
            status_code=503,
            code="cancellation_unconfirmed",
        ) from exc

    order = await db.get(
        VirtualNumberOrder,
        order_id,
    )

    if order is None:
        raise NotFoundError(
            "Virtual number order not found."
        )

    order.status = "CANCELLED"

    audit.record(
        db,
        action="virtual_number.cancelled",
        actor_user_id=principal.user.id,
        resource_type="virtual_number_order",
        resource_id=str(order.id),
        meta={
            "provider_request_id": order.provider_request_id,
            "refund": "not_assumed",
        },
    )

    await db.commit()

    txn = await db.get(
        Transaction,
        order.transaction_id,
    )

    if txn is None:
        raise RuntimeError(
            "Order transaction is missing."
        )

    return ok(
        await _fresh_view(db, txn, order),
        "Provider confirmed cancellation. No automatic refund was issued.",
    )


# ---------------------------------------------------------------------
# ADMIN ORDER MANAGEMENT
# ---------------------------------------------------------------------


@admin_router.get("/orders")
async def admin_orders(
    status: str | None = None,
    search: str | None = Query(
        default=None,
        max_length=100,
    ),
    country_id: int | None = Query(
        default=None,
        ge=0,
    ),
    from_date: date | None = None,
    to_date: date | None = None,
    principal: Principal = Depends(
        require_permission(Permission.TRANSACTIONS_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if from_date and to_date and from_date > to_date:
        raise VirtualNumberError(
            "from_date cannot be later than to_date.",
            status_code=422,
            code="invalid_date_range",
        )

    stmt = select(
        VirtualNumberOrder,
        Transaction,
    ).join(
        Transaction,
        Transaction.id == VirtualNumberOrder.transaction_id,
    )

    if status:
        stmt = stmt.where(
            VirtualNumberOrder.status == status.strip().upper()
        )

    if country_id is not None:
        stmt = stmt.where(
            VirtualNumberOrder.country_id == country_id
        )

    if from_date is not None:
        stmt = stmt.where(
            VirtualNumberOrder.created_at
            >= datetime.combine(
                from_date,
                time.min,
                tzinfo=UTC,
            )
        )

    if to_date is not None:
        stmt = stmt.where(
            VirtualNumberOrder.created_at
            < datetime.combine(
                to_date + timedelta(days=1),
                time.min,
                tzinfo=UTC,
            )
        )

    if search and search.strip():
        term = f"%{search.strip()}%"

        stmt = stmt.where(
            or_(
                Transaction.reference.ilike(term),
                VirtualNumberOrder.phone_number.ilike(term),
                VirtualNumberOrder.country_name.ilike(term),
                VirtualNumberOrder.service_name.ilike(term),
                cast(
                    VirtualNumberOrder.provider_request_id,
                    String,
                ).ilike(term),
                cast(
                    VirtualNumberOrder.user_id,
                    String,
                ).ilike(term),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                VirtualNumberOrder.created_at.desc()
            ).limit(500)
        )
    ).all()

    can_see_costs = has_permission(
        principal.user.role,
        Permission.FINANCE_PROFIT_READ,
    )

    output: list[dict[str, Any]] = []

    for order, txn in rows:
        item = _view(txn, order) | {
            "user_id": str(order.user_id),
            "provider_request_id": order.provider_request_id,
        }

        if can_see_costs:
            item |= {
                "provider_cost_kobo": order.provider_cost_kobo,
                "margin_kobo": (
                    order.selling_price_kobo
                    - order.provider_cost_kobo
                ),
            }

        output.append(item)

    return ok(output)


@admin_router.get("/provider-status")
async def provider_status(
    settings: Settings = Depends(get_app_settings),
    _: Principal = Depends(
        require_permission(Permission.PROVIDERS_MANAGE)
    ),
) -> dict[str, Any]:
    return ok({
        "enabled": settings.smsman_enabled,
        "configured": bool(
            settings.smsman_api_key.get_secret_value()
        ),
        "api_version": "2.0",
        "base_url": settings.smsman_base_url,
        "currency": settings.smsman_currency,
        "ngn_rate_configured": (
            settings.smsman_ngn_per_unit > 0
        ),
        "esim_enabled": False,
    })


# ---------------------------------------------------------------------
# ADMIN PRICING
# ---------------------------------------------------------------------


@admin_router.get("/pricing")
async def admin_pricing(
    settings: Settings = Depends(get_app_settings),
    _: Principal = Depends(
        require_permission(Permission.PRICING_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(
        VirtualNumberPricing,
        1,
    )

    pricing = _effective_pricing(
        settings,
        row,
    )

    return ok({
        "markup_percent": str(pricing["markup_percent"]),
        "fixed_fee_kobo": pricing["fixed_fee_kobo"],
        "min_price_kobo": pricing["min_price_kobo"],
        "max_price_kobo": pricing["max_price_kobo"],
        "enabled": pricing["enabled"],
    })


@admin_router.patch("/pricing")
async def update_admin_pricing(
    body: PricingPatch,
    principal: Principal = Depends(
        require_permission(Permission.PRICING_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(
        VirtualNumberPricing,
        1,
    )

    before = (
        {
            "markup_percent": str(row.markup_percent),
            "fixed_fee_kobo": row.fixed_fee_kobo,
            "min_price_kobo": row.min_price_kobo,
            "max_price_kobo": row.max_price_kobo,
            "enabled": row.enabled,
        }
        if row is not None
        else None
    )

    if row is None:
        row = VirtualNumberPricing(
            id=1,
            markup_percent=body.markup_percent,
            fixed_fee_kobo=body.fixed_fee_kobo,
            min_price_kobo=body.min_price_kobo,
            max_price_kobo=body.max_price_kobo,
            enabled=body.enabled,
        )

        db.add(row)

    else:
        row.markup_percent = body.markup_percent
        row.fixed_fee_kobo = body.fixed_fee_kobo
        row.min_price_kobo = body.min_price_kobo
        row.max_price_kobo = body.max_price_kobo
        row.enabled = body.enabled

    audit.record(
        db,
        action="virtual_number.pricing.changed",
        actor_user_id=principal.user.id,
        resource_type="virtual_number_pricing",
        resource_id="1",
        before=before,
        after=body.model_dump(mode="json"),
    )

    await db.commit()
    await db.refresh(row)

    return ok({
        "markup_percent": str(row.markup_percent),
        "fixed_fee_kobo": row.fixed_fee_kobo,
        "min_price_kobo": row.min_price_kobo,
        "max_price_kobo": row.max_price_kobo,
        "enabled": row.enabled,
    })


# ---------------------------------------------------------------------
# ADMIN RECONCILIATION
# ---------------------------------------------------------------------


@admin_router.post("/orders/{order_id}/resolve")
async def resolve_uncertain_order(
    order_id: uuid.UUID,
    body: ManualResolutionIn,
    principal: Principal = Depends(
        require_permission(Permission.TRANSACTIONS_RESOLVE)
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    order = (
        await db.execute(
            select(VirtualNumberOrder)
            .where(
                VirtualNumberOrder.id == order_id
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if order is None:
        raise NotFoundError(
            "Virtual number order not found."
        )

    txn = await db.get(
        Transaction,
        order.transaction_id,
    )

    if txn is None:
        raise VirtualNumberError(
            "The order has no associated transaction.",
            status_code=409,
            code="transaction_missing",
        )

    if txn.status not in {
        TxnStatus.PROCESSING.value,
        TxnStatus.UNKNOWN.value,
    }:
        raise VirtualNumberError(
            "Only uncertain orders can be reconciled.",
            status_code=409,
            code="order_not_reconcilable",
        )

    old_status = order.status

    if body.outcome == "SUCCESS":
        if (
            body.provider_request_id is None
            or body.phone_number is None
            or body.provider_cost_kobo is None
        ):
            raise VirtualNumberError(
                "A confirmed provider request ID, number, and provider cost "
                "are required.",
                status_code=422,
                code="resolution_evidence_required",
            )

        order.provider_request_id = body.provider_request_id
        order.phone_number = body.phone_number
        order.status = "ACTIVE"
        txn.provider_reference = str(
            body.provider_request_id
        )

        # Persist provider evidence before attempting settlement.
        await db.commit()

        result = ProviderResult(
            Outcome.SUCCESS,
            provider_reference=str(
                body.provider_request_id
            ),
            amount_charged=Money(
                body.provider_cost_kobo
            ),
            message=body.note,
        )

    else:
        order.status = "FAILED"
        order.failure_reason = (
            "Provider failure confirmed by authorized administrator."
        )

        result = ProviderResult(
            Outcome.FAILED,
            message=body.note,
        )

    audit.record(
        db,
        action="virtual_number.manual_reconciliation",
        actor_user_id=principal.user.id,
        resource_type="virtual_number_order",
        resource_id=str(order.id),
        before={"status": old_status},
        after={"outcome": body.outcome},
        meta={"note": body.note},
    )

    txn = await TransactionService(
        db,
        redis,
        settings,
        {},
    ).apply(
        txn.id,
        result,
        source="manual",
    )

    await db.commit()

    return ok(
        await _fresh_view(db, txn, order),
        "Virtual number order reconciled.",
    )


# ---------------------------------------------------------------------
# ADMIN CATALOGUE
# ---------------------------------------------------------------------


@admin_router.get("/catalogue")
async def admin_catalogue(
    request: Request,
    country_id: int | None = Query(
        default=None,
        ge=0,
    ),
    _: Principal = Depends(
        require_permission(Permission.PROVIDERS_MANAGE)
    ),
    settings: Settings = Depends(get_app_settings),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    _enabled(settings)

    provider = _provider(
        request,
        settings,
    )

    try:
        country_values, service_values = await _cached_catalogues(
            provider,
            redis,
        )

        output: dict[str, Any] = {
            "countries": _country_view(country_values),
            "services": _service_view(service_values),
            "fetched_at": datetime.now(UTC).isoformat(),
            "prices": [],
        }

        if country_id is None:
            return ok(output)

        raw_prices = await _cached_prices(
            provider,
            redis,
            country_id,
            admin=True,
        )

        price_index = _price_index(
            raw_prices,
            country_id,
        )

        pricing_row = await db.get(
            VirtualNumberPricing,
            1,
        )

        country = _catalogue_country(
            country_values,
            country_id,
        )

        country_name = (
            str(country.get("title", ""))
            if country
            else ""
        )

        drop_reasons: Counter[str] = Counter()
        services_without_quote = 0

        for service_item in service_values:
            service_id = _safe_int(
                service_item.get("id"),
                -1,
            )
            service_name = service_item.get("name")

            if service_id < 0 or not service_name:
                continue

            reasons: list[str] = []

            quote = _price_payload(
                raw_prices,
                country_id,
                service_id,
                settings,
                pricing_row,
                price_index=price_index,
                reject=reasons,
            )

            if quote is None:
                if reasons == ["no_quote_for_service"]:
                    services_without_quote += 1
                else:
                    drop_reasons.update(reasons)

                continue

            output["prices"].append({
                "country_id": country_id,
                "country_name": country_name,
                "application_id": service_id,
                "service_name": str(service_name),
                "service_code": service_item.get("code"),
                **quote,
            })

        output["prices"].sort(
            key=lambda item: item["service_name"].casefold()
        )

        pricing = _effective_pricing(
            settings,
            pricing_row,
        )

        output["price_diagnostics"] = {
            "requested_country_id": country_id,
            "country_found": country is not None,
            "provider_price_records_for_country": len(price_index),
            "services_in_catalogue": len(service_values),
            "services_without_provider_quote": services_without_quote,
            "priced_services_returned": len(output["prices"]),
            "drop_reasons": dict(drop_reasons),
            "pricing_rule_enabled": pricing["enabled"],
            "ngn_conversion_rate_configured": (
                settings.smsman_ngn_per_unit > 0
            ),
            "provider_currency": settings.smsman_currency,
            "ngn_per_unit": str(
                settings.smsman_ngn_per_unit
            ),
            "markup_percent": str(
                pricing["markup_percent"]
            ),
            "fixed_fee_kobo": pricing["fixed_fee_kobo"],
            "min_price_kobo": pricing["min_price_kobo"],
            "max_price_kobo": pricing["max_price_kobo"],
        }

        return ok(output)

    except SMSManError as exc:
        raise VirtualNumberError(
            "Provider catalogue could not be refreshed.",
            status_code=503,
            code="provider_unavailable",
        ) from exc


# ---------------------------------------------------------------------
# ADMIN REPORT
# ---------------------------------------------------------------------


@admin_router.get("/report")
async def admin_report(
    _: Principal = Depends(
        require_permission(Permission.FINANCE_PROFIT_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                VirtualNumberOrder.status,
                func.count(VirtualNumberOrder.id),
                func.coalesce(
                    func.sum(
                        VirtualNumberOrder.selling_price_kobo
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        VirtualNumberOrder.provider_cost_kobo
                    ),
                    0,
                ),
            ).group_by(
                VirtualNumberOrder.status
            )
        )
    ).all()

    report: dict[str, Any] = {
        "orders": 0,
        "sales_kobo": 0,
        "estimated_supplier_cost_kobo": 0,
        "estimated_margin_kobo": 0,
        "by_status": [],
    }

    for status, count, sales, costs in rows:
        count = int(count)
        sales = int(sales)
        costs = int(costs)
        fulfilled = status in FULFILLED_ORDER_STATUSES

        report["orders"] += count

        if fulfilled:
            report["sales_kobo"] += sales
            report["estimated_supplier_cost_kobo"] += costs

        report["by_status"].append({
            "status": status,
            "count": count,
            "sales_kobo": sales if fulfilled else 0,
            "estimated_supplier_cost_kobo": (
                costs if fulfilled else 0
            ),
            "estimated_margin_kobo": (
                sales - costs if fulfilled else 0
            ),
        })

    report["estimated_margin_kobo"] = (
        report["sales_kobo"]
        - report["estimated_supplier_cost_kobo"]
    )

    report["note"] = (
        "Supplier costs and margins are estimates until provider "
        "settlement data is independently reconciled."
    )

    return ok(report)
