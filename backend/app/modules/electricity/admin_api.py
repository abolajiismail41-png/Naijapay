import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.electricity.models import ElectricityDisco
from app.modules.electricity.sync import sync_electricity
from app.modules.providers.models import ProviderPrice
from app.modules.providers.prices import expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.purchase import PROVIDER

router = APIRouter(prefix="/api/v1/admin/electricity", tags=["admin-electricity"])
SAMPLE = Money.from_naira(5000)
Bps = Annotated[int, Field(strict=True, ge=0, le=2000)]
ServiceId = Annotated[str, Field(min_length=1, max_length=40)]


class NotSellableError(AppError):
    status_code, code = 422, "disco_not_sellable"
    user_message = "This disco cannot be listed: it needs a service id with a fresh cost, and a price above cost."


class DiscoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    name: str = Field(min_length=3, max_length=80)
    provider_disco_code: str = Field(min_length=1, max_length=40)
    prepaid_service_id: ServiceId | None = None
    postpaid_service_id: ServiceId | None = None
    prepaid_discount_bps: Bps | None = None
    postpaid_discount_bps: Bps | None = None


class DiscoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=3, max_length=80)
    provider_disco_code: str | None = Field(default=None, min_length=1, max_length=40)
    prepaid_service_id: ServiceId | None = None
    postpaid_service_id: ServiceId | None = None
    prepaid_discount_bps: Bps | None = None
    postpaid_discount_bps: Bps | None = None
    listed: bool | None = None
    active: bool | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10_000)] | None = None


async def _cost_row(db: AsyncSession, service_id: str | None) -> ProviderPrice | None:
    if not service_id:
        return None
    return (await db.execute(select(ProviderPrice).where(
        ProviderPrice.provider_code == PROVIDER, ProviderPrice.category == "ELECTRICITY",
        ProviderPrice.provider_service_id == service_id))).scalar_one_or_none()


async def _set_discount(db: AsyncSession, service_id: str, bps: int, actor: uuid.UUID) -> None:
    row = await _cost_row(db, service_id)
    if row is None:
        db.add(ProviderPrice(provider_code=PROVIDER, category="ELECTRICITY", scope_key=service_id,
                             provider_service_id=service_id, kind="DISCOUNT_BPS", value=bps, source="MANUAL", active=True))
    else:
        audit.record(db, action="provider_price.changed", actor_user_id=actor, resource_type="provider_price",
                     resource_id=f"ELECTRICITY:{service_id}", before={"value": row.value, "source": row.source},
                     after={"value": bps, "source": "MANUAL"})
        row.value, row.source, row.active = bps, "MANUAL", True


async def _samples(db: AsyncSession, discos: list[ElectricityDisco]) -> dict[tuple[uuid.UUID, str], Any]:
    keys, items = [], []
    for d in discos:
        for t in ("PREPAID", "POSTPAID"):
            row = await _cost_row(db, d.service_id(t))
            if row is not None and row.active:
                keys.append((d.id, t, row))
                items.append(([f"{d.code}:{t}", d.code], expected_cost(row, SAMPLE), SAMPLE))
    prices = await pricing.price_many(db, category="ELECTRICITY", provider_code=PROVIDER, items=items)
    return {(k[0], k[1]): (k[2], b) for k, b in zip(keys, prices)}


@router.get("/discos")
async def list_discos(_: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    discos = list((await db.execute(select(ElectricityDisco).order_by(ElectricityDisco.name))).scalars())
    sample = await _samples(db, discos)
    out = []
    for d in discos:
        types = {}
        for t in ("PREPAID", "POSTPAID"):
            if d.service_id(t):
                row, b = sample.get((d.id, t), (None, None))
                types[t] = {"service_id": d.service_id(t), "discount_bps": row.value if row else None,
                            "cost_source": row.source if row else None,
                            "sample_amount": SAMPLE.naira_str(), "sample_customer_price": b.customer_price.naira_str() if b else None,
                            "sample_gross_profit": b.gross_profit.naira_str() if b else None,
                            "sample_margin_pct": str(b.margin_pct) if b else None, "price_blocked": row is not None and b is None}
        out.append({"id": str(d.id), "code": d.code, "name": d.name, "provider_disco_code": d.provider_disco_code,
                    "listed": d.listed, "active": d.active, "sort_order": d.sort_order, "types": types})
    return ok(out)


@router.post("/discos", status_code=201)
async def create_disco(body: DiscoIn, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if (await db.execute(select(ElectricityDisco.id).where(ElectricityDisco.provider_code == PROVIDER,
                                                            ElectricityDisco.code == body.code))).first():
        raise ConflictError("A disco with this code already exists.")
    d = ElectricityDisco(provider_code=PROVIDER, code=body.code, name=body.name, provider_disco_code=body.provider_disco_code,
                         prepaid_service_id=body.prepaid_service_id, postpaid_service_id=body.postpaid_service_id)
    db.add(d)
    for sid, bps in ((body.prepaid_service_id, body.prepaid_discount_bps), (body.postpaid_service_id, body.postpaid_discount_bps)):
        if sid and bps is not None:
            await _set_discount(db, sid, bps, p.user.id)
    audit.record(db, action="electricity_disco.created", actor_user_id=p.user.id, resource_type="electricity_disco",
                 resource_id=body.code, after=body.model_dump())
    await db.commit()
    return ok({"id": str(d.id), "code": d.code, "listed": False})


@router.patch("/discos/{disco_id}")
async def patch_disco(disco_id: uuid.UUID, body: DiscoPatch, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
                      db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    d = await db.get(ElectricityDisco, disco_id)
    if d is None:
        raise NotFoundError("Disco not found.")
    before = {f: getattr(d, f) for f in ("name", "provider_disco_code", "prepaid_service_id", "postpaid_service_id", "listed", "active", "sort_order")}
    for f in ("name", "provider_disco_code", "prepaid_service_id", "postpaid_service_id", "active", "sort_order"):
        if (v := getattr(body, f)) is not None:
            setattr(d, f, v)
    for sid, bps in ((d.prepaid_service_id, body.prepaid_discount_bps), (d.postpaid_service_id, body.postpaid_discount_bps)):
        if sid and bps is not None:
            await _set_discount(db, sid, bps, p.user.id)
    await db.flush()
    if body.listed:
        sample = await _samples(db, [d])
        ok_types = [k for k, (row, b) in sample.items() if b is not None and is_fresh(row, settings.provider_cost_max_age_h)]
        if not (d.active and ok_types):
            raise NotSellableError()
    if body.listed is not None:
        d.listed = body.listed
    audit.record(db, action="electricity_disco.changed", actor_user_id=p.user.id, resource_type="electricity_disco",
                 resource_id=d.code, before=before, after=body.model_dump(exclude_none=True))
    await db.commit()
    return ok({"id": str(d.id), "listed": d.listed, "active": d.active})


@router.post("/sync")
async def sync(request: Request, p: Principal = Depends(require_permission(Permission.PRICING_MANAGE)),
               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await sync_electricity(db, request.app.state.bill_providers[PROVIDER], PROVIDER, actor_id=p.user.id)
    return ok({"discos_created": r.discos_created, "prices_created": r.prices_created,
               "prices_updated": r.prices_updated, "rejected": r.rejected})
