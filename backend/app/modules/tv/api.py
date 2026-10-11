import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import AppError
from app.core.money import Money
from app.modules.auth.deps import PinStepUp, Principal, current_principal, require_pin_step_up
from app.modules.providers.prices import tv_price, expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.models import TVOrder
from app.modules.transactions.purchase import PROVIDER, PurchaseService
from app.modules.transactions.views import mask, public_view
from app.modules.tv.models import TVProduct
from app.modules.tv.service import TVService

router = APIRouter(prefix="/api/v1/tv", tags=["tv-subscriptions"])
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")]


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    smartcard_number: str = Field(min_length=8, max_length=24, pattern=r"^\d+$")


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    product_id: uuid.UUID


class BuyIn(QuoteIn):
    confirmed_price_kobo: Annotated[int, Field(strict=True, gt=0)]


def _ts(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_app_settings)) -> TVService:
    return TVService(db, redis, settings, request.app.state.bill_providers)


def _ps(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_app_settings)) -> PurchaseService:
    return PurchaseService(db, redis, settings)


class TVProductUnavailableError(AppError):
    status_code, code = 404, "tv_product_unavailable"
    user_message = "This TV package is not available."


async def load_product(db: AsyncSession, product_id: uuid.UUID) -> TVProduct:
    p = await db.get(TVProduct, product_id)
    if p is None or not (p.listed and p.active and p.provider_code == PROVIDER):
        raise TVProductUnavailableError()
    return p


async def product_price(db: AsyncSession, settings: Settings, p: TVProduct) -> tuple[Money, Any] | None:
    row = await tv_price(db, PROVIDER, p.provider_service_id)
    if row is None or not is_fresh(row, settings.provider_cost_max_age_h):
        return None
    cost = expected_cost(row, Money(0))
    scopes = [f"PLAN:{p.provider_service_id}", p.operator_code]
    (breakdown,) = await pricing.price_many(db, category="TV", provider_code=PROVIDER, items=[(scopes, cost)])
    return (breakdown.customer_price, row) if breakdown else None


@router.get("/operators")
async def operators(_: Principal = Depends(current_principal), svc: TVService = Depends(_ts)) -> dict[str, Any]:
    return ok(await svc.operators())


@router.get("/plans")
async def plans(operator_code: str, _: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                settings: Settings = Depends(get_app_settings), svc: TVService = Depends(_ts)) -> dict[str, Any]:
    svc.check_enabled()
    rows = (await db.execute(select(TVProduct).where(TVProduct.provider_code == PROVIDER,
        TVProduct.operator_code == operator_code, TVProduct.listed.is_(True), TVProduct.active.is_(True))
        .order_by(TVProduct.sort_order, TVProduct.name))).scalars()
    out = []
    for p in rows:
        result = await product_price(db, settings, p)
        if result:
            price, _ = result
            out.append({"id": str(p.id), "operator_code": p.operator_code, "operator": p.operator_name,
                        "name": p.name, "price_kobo": price.kobo, "price": price.naira_str()})
    return ok(out)


@router.post("/validate")
async def validate(body: ValidateIn, p: Principal = Depends(current_principal), svc: TVService = Depends(_ts)) -> dict[str, Any]:
    vid, info, operator_name = await svc.validate(p.user, body.operator_code, body.smartcard_number)
    return ok({"validation_id": vid, "operator_code": body.operator_code, "operator": operator_name,
               "smartcard_number": mask(info.smartcard_number), "customer_name": info.customer_name,
               "current_bouquet": info.current_bouquet, "expires_in_s": svc.settings.meter_validation_ttl_s})


@router.post("/quote")
async def quote(body: QuoteIn, step: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                svc: TVService = Depends(_ts), ps: PurchaseService = Depends(_ps)) -> dict[str, Any]:
    svc.check_enabled()
    product = await load_product(db, body.product_id)
    target = await svc.load_target(step.user, body.validation_id, product)
    breakdown, _rule, _row = await ps.quote_tv(target)
    return ok({"product_id": str(product.id), "operator": product.operator_name, "product": product.name,
               "customer_name": target.customer_name, "smartcard_number": mask(target.smartcard_number),
               "price_kobo": breakdown.customer_price.kobo, "price": breakdown.customer_price.naira_str()})


@router.post("", status_code=202)
async def buy(body: BuyIn, request: Request, idempotency_key: IdemKey,
              step: PinStepUp = Depends(require_pin_step_up), svc: TVService = Depends(_ts),
              ps: PurchaseService = Depends(_ps), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    svc.check_enabled()
    product = await load_product(db, body.product_id)
    target = await svc.load_target(step.principal.user, body.validation_id, product)
    txn = await ps.create_tv(step.principal.user, target, body.confirmed_price_kobo,
                             idempotency_key, step.jti, step.expires_at)
    if txn.status == "PENDING":
        try:
            request.app.state.dispatcher.enqueue_execute(txn.id)
        except Exception:  # the transaction sweeper is the durable fallback
            pass
    return ok(public_view(txn, await db.get(TVOrder, txn.id)), "Your request has been received.")
