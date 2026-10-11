import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_app_settings, get_db, ok
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.providers.models import ProviderPrice
from app.modules.providers.prices import expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.purchase import PROVIDER
from app.modules.tv.models import TVProduct

router = APIRouter(prefix="/api/v1/admin/tv/products", tags=["admin-tv"])
Cost = Annotated[int, Field(strict=True, gt=0)]


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_code: str = Field(pattern=r"^[A-Z0-9_-]{2,20}$")
    operator_name: str = Field(min_length=2, max_length=60)
    provider_operator_id: str = Field(min_length=1, max_length=40)
    provider_service_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=80)
    cost_kobo: Cost


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=80)
    operator_name: str | None = Field(default=None, min_length=2, max_length=60)
    provider_operator_id: str | None = Field(default=None, min_length=1, max_length=40)
    cost_kobo: Cost | None = None
    listed: bool | None = None
    active: bool | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10000)] | None = None


class NotSellableError(AppError):
    status_code, code = 422, "product_not_sellable"
    user_message = "This package cannot be listed until it has a valid provider cost and customer price."


async def _price_row(db: AsyncSession, sid: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(ProviderPrice.provider_code == PROVIDER,
        ProviderPrice.category == "TV", ProviderPrice.provider_service_id == sid))).scalar_one_or_none()


async def _set_cost(db: AsyncSession, sid: str, kobo: int, actor: uuid.UUID) -> None:
    row = await _price_row(db, sid)
    if row is None:
        db.add(ProviderPrice(provider_code=PROVIDER, category="TV", scope_key=f"PLAN:{sid}",
            provider_service_id=sid, kind="FIXED_KOBO", value=kobo, source="MANUAL", active=True))
    else:
        audit.record(db, action="provider_price.changed", actor_user_id=actor, resource_type="provider_price",
            resource_id=f"TV:{sid}", before={"value": row.value, "source": row.source},
            after={"value": kobo, "source": "MANUAL"})
        row.value, row.kind, row.source, row.active = kobo, "FIXED_KOBO", "MANUAL", True


async def _sample(db: AsyncSession, p: TVProduct) -> tuple[ProviderPrice | None, Any]:
    row = await _price_row(db, p.provider_service_id)
    if row is None or not row.active:
        return row, None
    scopes = [f"PLAN:{p.provider_service_id}", p.operator_code]
    (b,) = await pricing.price_many(db, category="TV", provider_code=PROVIDER,
        items=[(scopes, expected_cost(row, Money(0)))])
    return row, b


@router.get("")
async def list_products(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    out = []
    for p in (await db.execute(select(TVProduct).order_by(TVProduct.operator_name, TVProduct.sort_order, TVProduct.name))).scalars():
        row, b = await _sample(db, p)
        out.append({"id": str(p.id), "operator_code": p.operator_code, "operator_name": p.operator_name,
            "provider_operator_id": p.provider_operator_id, "provider_service_id": p.provider_service_id,
            "name": p.name, "listed": p.listed, "active": p.active, "sort_order": p.sort_order,
            "unit_cost": Money(row.value).naira_str() if row else None,
            "unit_price": b.customer_price.naira_str() if b else None,
            "price_blocked": row is not None and b is None})
    return ok(out)


@router.post("", status_code=201)
async def create_product(body: ProductIn, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if (await db.execute(select(TVProduct.id).where(TVProduct.provider_code == PROVIDER,
            TVProduct.provider_service_id == body.provider_service_id))).first():
        raise ConflictError("A TV package with this provider service ID already exists.")
    prod = TVProduct(provider_code=PROVIDER, operator_code=body.operator_code, operator_name=body.operator_name,
        provider_operator_id=body.provider_operator_id, provider_service_id=body.provider_service_id, name=body.name)
    db.add(prod)
    await _set_cost(db, body.provider_service_id, body.cost_kobo, p.user.id)
    audit.record(db, action="tv_product.created", actor_user_id=p.user.id, resource_type="tv_product",
                 resource_id=body.provider_service_id, after=body.model_dump())
    await db.commit()
    return ok({"id": str(prod.id), "listed": False})


@router.patch("/{product_id}")
async def patch_product(product_id: uuid.UUID, body: ProductPatch,
                        p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                        db: AsyncSession = Depends(get_db), settings=Depends(get_app_settings)) -> dict[str, Any]:
    prod = await db.get(TVProduct, product_id)
    if prod is None:
        raise NotFoundError("TV package not found.")
    before = {f: getattr(prod, f) for f in ("name", "operator_name", "provider_operator_id", "provider_service_id", "listed", "active", "sort_order")}
    for f in ("name", "operator_name", "provider_operator_id", "active", "sort_order"):
        if (value := getattr(body, f)) is not None:
            setattr(prod, f, value)
    if body.cost_kobo is not None:
        await _set_cost(db, prod.provider_service_id, body.cost_kobo, p.user.id)
    await db.flush()
    if body.listed:
        row, b = await _sample(db, prod)
        if not (prod.active and row is not None and b is not None and is_fresh(row, settings.provider_cost_max_age_h)):
            raise NotSellableError()
    if body.listed is not None:
        prod.listed = body.listed
    audit.record(db, action="tv_product.changed", actor_user_id=p.user.id, resource_type="tv_product",
        resource_id=prod.provider_service_id, before=before, after=body.model_dump(exclude_none=True))
    await db.commit()
    return ok({"id": str(prod.id), "listed": prod.listed, "active": prod.active})
