import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.money import Money
from app.core.phone import Phone
from app.modules.auth.deps import PinStepUp, Principal, current_principal, require_pin_step_up
from app.modules.providers.models import DataPlan, ProviderPrice
from app.modules.providers.prices import expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.models import DataOrder
from app.modules.transactions.purchase import PROVIDER, PurchaseService
from app.modules.transactions.views import public_view

router = APIRouter(prefix="/api/v1/data", tags=["data"])
Network = Literal["MTN", "AIRTEL", "GLO", "9MOBILE"]
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")]
_CACHE_TTL_S = 60


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: uuid.UUID


class BuyIn(QuoteIn):
    phone: Phone
    confirmed_price_kobo: Annotated[int, Field(strict=True, gt=0)]
    confirm_network: bool = False


def scopes_of(plan: DataPlan) -> list[str]:
    """Pricing scopes from most to least specific: this plan, network+type, network."""
    return [f"PLAN:{plan.provider_service_id}", f"{plan.network}:{plan.data_type}", plan.network]


def _svc(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
         settings: Settings = Depends(get_app_settings)) -> PurchaseService:
    return PurchaseService(db, redis, settings)


async def sellable_plans(db: AsyncSession, settings: Settings, network: str | None = None) -> list[tuple[DataPlan, Money]]:
    q = (select(DataPlan, ProviderPrice).join(ProviderPrice, (ProviderPrice.provider_code == DataPlan.provider_code)
         & (ProviderPrice.category == "DATA") & (ProviderPrice.provider_service_id == DataPlan.provider_service_id)
         & ProviderPrice.active.is_(True)).where(DataPlan.listed.is_(True), DataPlan.active.is_(True),
                                                   DataPlan.provider_code == PROVIDER))
    if network:
        q = q.where(DataPlan.network == network)
    rows = [(p, expected_cost(r, Money(0))) for p, r in (await db.execute(q)).all()
            if is_fresh(r, settings.provider_cost_max_age_h)]
    prices = await pricing.price_many(db, category="DATA", provider_code=PROVIDER,
                                      items=[(scopes_of(p), c) for p, c in rows])
    out = [(p, b.customer_price) for (p, _), b in zip(rows, prices) if b is not None]
    return sorted(out, key=lambda x: (x[1].kobo, x[0].name))


@router.get("/networks")
async def networks(_: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                   settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    return ok(sorted({p.network for p, _ in await sellable_plans(db, settings)}))


@router.get("/plans")
async def plans(network: Network = Query(), _: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                redis: Redis = Depends(get_redis), settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    key = f"catalogue:data:{network}"
    if (cached := await redis.get(key)):
        return ok(json.loads(cached))
    items = [{"id": str(p.id), "network": p.network, "name": p.name, "type": p.data_type, "validity": p.validity,
              "price_kobo": price.kobo, "price": price.naira_str()} for p, price in await sellable_plans(db, settings, network)]
    await redis.set(key, json.dumps(items), ex=_CACHE_TTL_S)  # public data only: no costs ever enter this cache
    return ok(items)


@router.post("/quote")
async def quote(body: QuoteIn, _: Principal = Depends(current_principal), svc: PurchaseService = Depends(_svc)) -> dict[str, Any]:
    b, _rule, _row, plan = await svc.quote_data(body.plan_id)
    return ok({"plan_id": str(plan.id), "network": plan.network, "name": plan.name, "validity": plan.validity,
               "price_kobo": b.customer_price.kobo, "price": b.customer_price.naira_str()})


@router.post("", status_code=202)
async def buy(body: BuyIn, request: Request, idempotency_key: IdemKey, step: PinStepUp = Depends(require_pin_step_up),
              svc: PurchaseService = Depends(_svc), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    txn = await svc.create_data(step.principal.user, body.plan_id, body.phone, body.confirmed_price_kobo,
                                idempotency_key, step.jti, step.expires_at, body.confirm_network)
    if txn.status == "PENDING":
        try:
            request.app.state.dispatcher.enqueue_execute(txn.id)
        except Exception:  # noqa: BLE001  the sweeper picks it up
            pass
    return ok(public_view(txn, await db.get(DataOrder, txn.id)), "Your request has been received.")
