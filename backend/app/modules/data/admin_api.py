import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_prefix
from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import AppError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.data.api import scopes_of
from app.modules.providers.models import DataPlan, ProviderPrice
from app.modules.providers.prices import expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.purchase import PROVIDER

router = APIRouter(prefix="/api/v1/admin/data-plans", tags=["admin-data-plans"])


class PlanNotSellableError(AppError):
    status_code, code = 422, "plan_not_sellable"
    user_message = "This plan cannot be listed: it has no fresh provider cost, or its price would be below cost."


class PatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listed: bool | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None


async def _rows(db: AsyncSession) -> list[tuple[DataPlan, ProviderPrice | None]]:
    q = (select(DataPlan, ProviderPrice).outerjoin(ProviderPrice, (ProviderPrice.provider_code == DataPlan.provider_code)
         & (ProviderPrice.category == "DATA") & (ProviderPrice.provider_service_id == DataPlan.provider_service_id))
         .order_by(DataPlan.network, DataPlan.sort_order, DataPlan.name))
    return [(p, r) for p, r in (await db.execute(q)).all()]


def _breakdowns(items: list[tuple[DataPlan, ProviderPrice | None]], prices: list[Any]) -> list[Any]:
    it = iter(prices)
    return [next(it) if r is not None else None for _, r in items]


@router.get("")
async def list_plans(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = await _rows(db)
    priced = [(p, r) for p, r in rows if r is not None]
    bs = _breakdowns(rows, await pricing.price_many(
        db, category="DATA", provider_code=PROVIDER, items=[(scopes_of(p), expected_cost(r, Money(0))) for p, r in priced]))
    out = []
    for (p, r), b in zip(rows, bs):
        out.append({"id": str(p.id), "provider_service_id": p.provider_service_id, "network": p.network, "name": p.name,
                    "type": p.data_type, "validity": p.validity, "listed": p.listed, "active": p.active,
                    "sort_order": p.sort_order, "cost": Money(r.value).naira_str() if r else None,
                    "cost_source": r.source if r else None, "cost_synced_at": r.synced_at.isoformat() if r and r.synced_at else None,
                    "customer_price": b.customer_price.naira_str() if b else None,
                    "gross_profit": b.gross_profit.naira_str() if b else None, "margin_pct": str(b.margin_pct) if b else None,
                    "price_blocked": b is None})
    return ok(out)


@router.patch("/{plan_id}")
async def patch_plan(plan_id: uuid.UUID, body: PatchIn, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                     db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
                     settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    plan = await db.get(DataPlan, plan_id)
    if plan is None:
        raise NotFoundError("Plan not found.")
    before = {"listed": plan.listed, "sort_order": plan.sort_order}
    if body.listed:
        row = (await db.execute(select(ProviderPrice).where(
            ProviderPrice.provider_code == plan.provider_code, ProviderPrice.category == "DATA",
            ProviderPrice.provider_service_id == plan.provider_service_id, ProviderPrice.active.is_(True)))).scalar_one_or_none()
        sellable = plan.active and row is not None and is_fresh(row, settings.provider_cost_max_age_h)
        if sellable:
            (b,) = await pricing.price_many(db, category="DATA", provider_code=PROVIDER,
                                            items=[(scopes_of(plan), expected_cost(row, Money(0)))])
            sellable = b is not None
        if not sellable:
            raise PlanNotSellableError()
    if body.listed is not None:
        plan.listed = body.listed
    if body.sort_order is not None:
        plan.sort_order = body.sort_order
    audit.record(db, action="data_plan.listing_changed", actor_user_id=p.user.id, resource_type="data_plan",
                 resource_id=str(plan.id), before=before, after={"listed": plan.listed, "sort_order": plan.sort_order})
    await db.commit()
    await invalidate_prefix(redis, "catalogue:")
    return ok({"id": str(plan.id), "listed": plan.listed, "sort_order": plan.sort_order})
