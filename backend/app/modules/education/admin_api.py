import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, ok
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.education.api import scopes_of
from app.modules.education.models import EducationProduct
from app.modules.providers.models import ProviderPrice
from app.modules.providers.prices import expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.purchase import PROVIDER

router = APIRouter(prefix="/api/v1/admin/education/products", tags=["admin-education"])
Cost = Annotated[int, Field(strict=True, gt=0)]


class NotSellableError(AppError):
    status_code, code = 422, "product_not_sellable"
    user_message = "This product cannot be listed: it needs a provider cost, and a price above cost."


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    name: str = Field(min_length=3, max_length=80)
    provider_service_id: str = Field(min_length=1, max_length=40)
    cost_kobo: Cost                      # what the provider charges us for ONE pin
    max_quantity: Annotated[int, Field(strict=True, ge=1, le=20)] = 5


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=3, max_length=80)
    provider_service_id: str | None = Field(default=None, min_length=1, max_length=40)
    cost_kobo: Cost | None = None
    max_quantity: Annotated[int, Field(strict=True, ge=1, le=20)] | None = None
    listed: bool | None = None
    active: bool | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None


async def _cost(db: AsyncSession, sid: str) -> ProviderPrice | None:
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == PROVIDER, ProviderPrice.category == "EDUCATION",
        ProviderPrice.provider_service_id == sid))).scalar_one_or_none()


async def _set_cost(db: AsyncSession, sid: str, kobo: int, actor: uuid.UUID) -> None:
    row = await _cost(db, sid)
    if row is None:
        db.add(ProviderPrice(provider_code=PROVIDER, category="EDUCATION", scope_key=sid, provider_service_id=sid,
                             kind="FIXED_KOBO", value=kobo, source="MANUAL", active=True))
        return
    audit.record(db, action="provider_price.changed", actor_user_id=actor, resource_type="provider_price",
                 resource_id=f"EDUCATION:{sid}", before={"value": row.value, "source": row.source}, after={"value": kobo, "source": "MANUAL"})
    row.value, row.source, row.active = kobo, "MANUAL", True


async def _sample(db: AsyncSession, p: EducationProduct) -> tuple[ProviderPrice | None, Any]:
    row = await _cost(db, p.provider_service_id)
    if row is None or not row.active:
        return row, None
    (b,) = await pricing.price_many(db, category="EDUCATION", provider_code=PROVIDER,
                                    items=[(scopes_of(p), expected_cost(row, Money(0)))])
    return row, b


@router.get("")
async def list_products(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    out = []
    for p in (await db.execute(select(EducationProduct).order_by(EducationProduct.name))).scalars():
        row, b = await _sample(db, p)
        out.append({"id": str(p.id), "code": p.code, "name": p.name, "provider_service_id": p.provider_service_id,
                    "max_quantity": p.max_quantity, "listed": p.listed, "active": p.active, "sort_order": p.sort_order,
                    "unit_cost": Money(row.value).naira_str() if row else None, "cost_source": row.source if row else None,
                    "unit_price": b.customer_price.naira_str() if b else None,
                    "unit_gross_profit": b.gross_profit.naira_str() if b else None,
                    "unit_margin_pct": str(b.margin_pct) if b else None, "price_blocked": row is not None and b is None})
    return ok(out)


@router.post("", status_code=201)
async def create_product(body: ProductIn, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if (await db.execute(select(EducationProduct.id).where(
            EducationProduct.provider_code == PROVIDER, EducationProduct.provider_service_id == body.provider_service_id))).first():
        raise ConflictError("A product with this provider service id already exists.")
    prod = EducationProduct(provider_code=PROVIDER, code=body.code, name=body.name,
                            provider_service_id=body.provider_service_id, max_quantity=body.max_quantity)
    db.add(prod)
    await _set_cost(db, body.provider_service_id, body.cost_kobo, p.user.id)
    audit.record(db, action="education_product.created", actor_user_id=p.user.id, resource_type="education_product",
                 resource_id=body.code, after=body.model_dump())
    await db.commit()
    return ok({"id": str(prod.id), "code": prod.code, "listed": False})


@router.patch("/{product_id}")
async def patch_product(product_id: uuid.UUID, body: ProductPatch,
                        p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                        db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    prod = await db.get(EducationProduct, product_id)
    if prod is None:
        raise NotFoundError("Product not found.")
    before = {f: getattr(prod, f) for f in ("name", "provider_service_id", "max_quantity", "listed", "active", "sort_order")}
    for f in ("name", "provider_service_id", "max_quantity", "active", "sort_order"):
        if (v := getattr(body, f)) is not None:
            setattr(prod, f, v)
    if body.cost_kobo is not None:
        await _set_cost(db, prod.provider_service_id, body.cost_kobo, p.user.id)
    await db.flush()
    if body.listed:
        row, b = await _sample(db, prod)
        if not (prod.active and row is not None and b is not None and is_fresh(row, settings.provider_cost_max_age_h)):
            raise NotSellableError()
    if body.listed is not None:
        prod.listed = body.listed
    audit.record(db, action="education_product.changed", actor_user_id=p.user.id, resource_type="education_product",
                 resource_id=prod.code, before=before, after=body.model_dump(exclude_none=True))
    await db.commit()
    return ok({"id": str(prod.id), "listed": prod.listed, "active": prod.active})
