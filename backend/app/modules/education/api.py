import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.crypto import decrypt
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import AppError, NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import PinStepUp, Principal, current_principal, require_pin_step_up
from app.modules.education.models import EducationProduct
from app.modules.providers.prices import education_price, expected_cost, is_fresh
from app.modules.services import interface as pricing
from app.modules.transactions.models import EducationOrder, Transaction
from app.modules.transactions.purchase import PROVIDER, ProductTarget, PurchaseService
from app.modules.transactions.views import public_view

router = APIRouter(prefix="/api/v1/education", tags=["education"])
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")]
Qty = Annotated[int, Field(strict=True, ge=1, le=100)]


class ProductUnavailableError(AppError):
    status_code, code = 404, "product_unavailable"
    user_message = "This product is not available."


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: uuid.UUID
    quantity: Qty = 1


class BuyIn(QuoteIn):
    confirmed_price_kobo: Annotated[int, Field(strict=True, gt=0)]


def scopes_of(p: EducationProduct) -> list[str]:
    return [f"PRODUCT:{p.provider_service_id}", p.code]


def target_of(p: EducationProduct) -> ProductTarget:
    return ProductTarget(p.id, p.code, p.name, p.provider_service_id, p.max_quantity)


def _ps(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_app_settings)) -> PurchaseService:
    return PurchaseService(db, redis, settings)


async def load_product(db: AsyncSession, product_id: uuid.UUID) -> EducationProduct:
    p = await db.get(EducationProduct, product_id)
    if p is None or not (p.listed and p.active):
        raise ProductUnavailableError()
    return p


@router.get("/products")
async def products(_: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                   settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    rows = []
    for p in (await db.execute(select(EducationProduct).where(
            EducationProduct.listed.is_(True), EducationProduct.active.is_(True), EducationProduct.provider_code == PROVIDER)
            .order_by(EducationProduct.sort_order, EducationProduct.name))).scalars():
        price = await education_price(db, PROVIDER, p.provider_service_id)
        if price is not None and is_fresh(price, settings.provider_cost_max_age_h):
            rows.append((p, expected_cost(price, Money(0))))
    bs = await pricing.price_many(db, category="EDUCATION", provider_code=PROVIDER, items=[(scopes_of(p), c) for p, c in rows])
    return ok([{"id": str(p.id), "code": p.code, "name": p.name, "max_quantity": min(p.max_quantity, settings.education_max_quantity),
                "unit_price_kobo": b.customer_price.kobo, "unit_price": b.customer_price.naira_str()}
               for (p, _), b in zip(rows, bs) if b is not None])


@router.post("/quote")
async def quote(body: QuoteIn, _: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db),
                ps: PurchaseService = Depends(_ps)) -> dict[str, Any]:
    p = await load_product(db, body.product_id)
    b, _rule, _row = await ps.quote_education(target_of(p), body.quantity)
    unit = Money(b.customer_price.kobo // body.quantity)
    return ok({"product": p.name, "quantity": body.quantity, "unit_price_kobo": unit.kobo, "unit_price": unit.naira_str(),
               "price_kobo": b.customer_price.kobo, "price": b.customer_price.naira_str()})


@router.post("", status_code=202)
async def buy(body: BuyIn, request: Request, idempotency_key: IdemKey, step: PinStepUp = Depends(require_pin_step_up),
              ps: PurchaseService = Depends(_ps), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    p = await load_product(db, body.product_id)
    txn = await ps.create_education(step.principal.user, target_of(p), body.quantity, body.confirmed_price_kobo,
                                    idempotency_key, step.jti, step.expires_at)
    if txn.status == "PENDING":
        try:
            request.app.state.dispatcher.enqueue_execute(txn.id)
        except Exception:  # noqa: BLE001  the sweeper picks it up
            pass
    return ok(public_view(txn, await db.get(EducationOrder, txn.id)), "Your request has been received.")


@router.get("/{reference}/pins")
async def pins(reference: Annotated[str, Path(pattern=r"^txn_[0-9a-f]{32}$")], p: Principal = Depends(current_principal),
               db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
               settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    """The only place PINs are returned. Owner-only, rate-limited, audited, never cached."""
    await ratelimit.hit(redis, f"rl:pins:{p.user.id}", 30, 3600)
    row = (await db.execute(select(Transaction, EducationOrder).join(
        EducationOrder, EducationOrder.transaction_id == Transaction.id).where(
        Transaction.reference == reference, Transaction.user_id == p.user.id))).first()
    if row is None or row[0].status != "SUCCESSFUL" or row[1].pins_status not in ("DELIVERED", "PARTIAL") or not row[1].pins_ciphertext:
        raise NotFoundError("No PINs are available for this transaction.")
    txn, order = row
    items = json.loads(decrypt(settings.encryption_key.get_secret_value(), order.pins_ciphertext, txn.reference))
    audit.record(db, action="pins.viewed", actor_user_id=p.user.id, resource_type="transaction", resource_id=txn.reference)
    await db.commit()
    return ok({"product": order.product_name, "ordered": order.quantity, "received": len(items), "complete": len(items) >= order.quantity,
               "pins": items})
