from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_prefix
from app.core.deps import get_db, get_redis, ok
from app.core.errors import ForbiddenError
from app.core.money import Money
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission, has_permission
from app.modules.providers import prices as provider_prices
from app.modules.providers.models import ProviderPrice
from app.modules.services.models import PricingRule
from app.modules.services.pricing import Method, RuleParams, compute
from app.modules.services.rules import create_rule_version, rule_dict

router = APIRouter(prefix="/api/v1/admin/pricing", tags=["admin-pricing"])
Kobo = Annotated[int, Field(strict=True, ge=0)]
Bps = Annotated[int, Field(strict=True, ge=0, le=10_000)]
Category = Literal["AIRTIME", "DATA", "ELECTRICITY", "TV", "EDUCATION"]


class _Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["PERCENT_MARKUP", "FIXED_MARKUP", "CUSTOM_PRICE", "FACE_VALUE"]
    markup_bps: Annotated[int, Field(strict=True, ge=-5_000, le=100_000)] | None = None
    markup_kobo: Annotated[int, Field(strict=True)] | None = None
    custom_price_kobo: Annotated[int, Field(strict=True, gt=0)] | None = None
    fee_kobo: Kobo = 0
    discount_bps: Bps = 0
    discount_kobo: Kobo = 0
    referral_bps: Bps = 0
    rounding_kobo: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 1
    cap_at_face: bool = False
    allow_subsidy: bool = False

    @model_validator(mode="after")
    def _method_fields(self) -> "_Pricing":
        needed = {"PERCENT_MARKUP": self.markup_bps, "FIXED_MARKUP": self.markup_kobo,
                  "CUSTOM_PRICE": self.custom_price_kobo, "FACE_VALUE": 0}[self.method]
        if needed is None:
            raise ValueError(f"{self.method} requires its matching amount field")
        return self


class RuleIn(_Pricing):
    category: Category
    provider_code: str | None = Field(default=None, max_length=20)
    scope_key: str | None = Field(default=None, max_length=40)
    tier: str = Field(default="DEFAULT", max_length=20)
    subsidy_reason: str | None = Field(default=None, max_length=200)
    note: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def _subsidy_needs_reason(self) -> "RuleIn":
        if self.allow_subsidy and not self.subsidy_reason:
            raise ValueError("allow_subsidy requires subsidy_reason")
        return self


class PreviewIn(_Pricing):
    provider_cost_kobo: Annotated[int, Field(strict=True, gt=0)]
    face_value_kobo: Annotated[int, Field(strict=True, gt=0)] | None = None
    referral_applicable: bool = False

    @model_validator(mode="after")
    def _face_needed(self) -> "PreviewIn":
        if self.method == "FACE_VALUE" and self.face_value_kobo is None:
            raise ValueError("FACE_VALUE needs face_value_kobo")
        return self


def _n(m: Money) -> str:
    return m.naira_str()


def _rule_out(r: PricingRule) -> dict[str, Any]:
    d = rule_dict(r)
    d.update(id=str(r.id), active=r.active, created_at=r.created_at.isoformat(),
             markup_percent=f"{Decimal(r.markup_bps) / 100:.2f}" if r.markup_bps is not None else None)
    return d


@router.get("/rules")
async def list_rules(category: Category | None = None, active_only: bool = True,
                     _: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = select(PricingRule).order_by(PricingRule.created_at.desc(), PricingRule.id.desc())
    if category:
        q = q.where(PricingRule.category == category)
    if active_only:
        q = q.where(PricingRule.active.is_(True))
    return ok([_rule_out(r) for r in (await db.execute(q.limit(200))).scalars()])


@router.post("/rules", status_code=201)
async def create_rule(body: RuleIn, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                      db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    if body.allow_subsidy and not has_permission(p.user.role, Permission.PRICING_SUBSIDY):
        raise ForbiddenError("Only a super admin may allow selling below provider cost.")
    rule = await create_rule_version(db, p.user.id, body.model_dump())
    await db.commit()
    await invalidate_prefix(redis, "catalogue:")
    return ok(_rule_out(rule), "Pricing rule saved. It applies to new transactions only.")


@router.post("/preview")
async def preview(body: PreviewIn, _: Principal = Depends(require_permission(Permission.PRICING_MANAGE))
                  ) -> dict[str, Any]:
    params = RuleParams(**body.model_dump(include=set(RuleParams.__dataclass_fields__)))
    face = Money(body.face_value_kobo) if body.face_value_kobo else None
    b = compute(Money(body.provider_cost_kobo), params, face=face, referral_applicable=body.referral_applicable,
                enforce=False)
    return ok({
        "provider_cost": _n(b.cost), "markup": _n(b.markup), "fee": _n(b.fee), "list_price": _n(b.list_price),
        "discount": _n(b.discount), "customer_price": _n(b.customer_price),
        "customer_price_kobo": b.customer_price.kobo, "gross_profit_before_discount": _n(b.gross_profit_before_discount),
        "gross_profit": _n(b.gross_profit), "gross_profit_kobo": b.gross_profit.kobo,
        "referral_commission": _n(b.referral_commission), "net_contribution": _n(b.net_contribution),
        "margin_pct": str(b.margin_pct), "capped_to_face_value": b.capped,
        "blocked": b.below_cost and not body.allow_subsidy,
        "block_reason": "Customer price is below provider cost." if b.below_cost and not body.allow_subsidy else None})


@router.get("/costs")
async def list_costs(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(select(ProviderPrice).order_by(ProviderPrice.category, ProviderPrice.scope_key))).scalars()
    return ok([{"provider": r.provider_code, "category": r.category, "scope": r.scope_key,
                "provider_service_id": r.provider_service_id, "kind": r.kind, "value": r.value, "source": r.source,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None} for r in rows])


@router.post("/costs/sync")
async def sync_costs(request: Request, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                     db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    provider = request.app.state.bill_providers["inlomax"]
    a = await provider_prices.sync_costs(db, provider, "inlomax", actor_id=p.user.id)
    d = await provider_prices.sync_data_plans(db, provider, "inlomax", actor_id=p.user.id)
    await invalidate_prefix(redis, "catalogue:")
    return ok({"airtime": {"updated": a.updated, "unchanged": a.unchanged, "rejected": a.rejected},
               "data": {"created": d.created, "updated": d.updated, "deactivated": d.deactivated,
                        "rejected": d.rejected, "suspicious": d.suspicious}})
