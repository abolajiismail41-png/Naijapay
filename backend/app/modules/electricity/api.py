import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import Settings
from app.core.crypto import decrypt
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import NotFoundError
from app.core.money import Money
from app.modules.audit import service as audit
from app.modules.auth.deps import PinStepUp, Principal, current_principal, require_pin_step_up
from app.modules.electricity.service import ElectricityService, MeterValidationExpiredError
from app.modules.transactions.models import ElectricityOrder, Transaction
from app.modules.transactions.purchase import PurchaseService
from app.modules.transactions.views import mask, public_view

router = APIRouter(prefix="/api/v1/electricity", tags=["electricity"])
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")]
Amount = Annotated[int, Field(strict=True, gt=0)]


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disco_id: uuid.UUID
    meter_type: Literal["PREPAID", "POSTPAID"]
    meter_number: str = Field(pattern=r"^\d{6,20}$")


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    amount_kobo: Amount


class BuyIn(QuoteIn):
    confirmed_price_kobo: Amount


def _es(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_app_settings)) -> ElectricityService:
    return ElectricityService(db, redis, settings, request.app.state.bill_providers)


def _ps(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
        settings: Settings = Depends(get_app_settings)) -> PurchaseService:
    return PurchaseService(db, redis, settings)


@router.get("/discos")
async def discos(_: Principal = Depends(current_principal), es: ElectricityService = Depends(_es)) -> dict[str, Any]:
    es.check_enabled()
    s = es.settings
    return ok([{"id": str(d.id), "code": d.code, "name": d.name, "meter_types": types,
                "min_kobo": s.electricity_min_kobo, "max_kobo": s.electricity_max_kobo} for d, types in await es.listed_discos()])


@router.post("/validate")
async def validate(body: ValidateIn, p: Principal = Depends(current_principal),
                   es: ElectricityService = Depends(_es)) -> dict[str, Any]:
    vid, t = await es.validate(p.user, body.disco_id, body.meter_type, body.meter_number)
    return ok({"validation_id": vid, "disco": t.disco_name, "meter_type": t.meter_type, "meter_number": mask(t.meter_number),
               "customer_name": t.customer_name, "address": t.customer_address,
               "min_kobo": max(es.settings.electricity_min_kobo, t.min_kobo), "expires_in_s": es.settings.meter_validation_ttl_s})


@router.post("/quote")
async def quote(body: QuoteIn, p: Principal = Depends(current_principal), es: ElectricityService = Depends(_es),
                ps: PurchaseService = Depends(_ps)) -> dict[str, Any]:
    es.check_enabled()
    t = await es.load(p.user, body.validation_id)
    b, _rule, _row = await ps.quote_electricity(t, body.amount_kobo)
    price, face = b.customer_price, Money(body.amount_kobo)
    fee = Money(max(price.kobo - face.kobo, 0))
    return ok({"amount_kobo": face.kobo, "amount": face.naira_str(), "service_fee_kobo": fee.kobo, "service_fee": fee.naira_str(),
               "price_kobo": price.kobo, "price": price.naira_str(), "meter_number": mask(t.meter_number),
               "customer_name": t.customer_name})


@router.post("", status_code=202)
async def buy(body: BuyIn, request: Request, idempotency_key: IdemKey, step: PinStepUp = Depends(require_pin_step_up),
              es: ElectricityService = Depends(_es), ps: PurchaseService = Depends(_ps),
              db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    es.check_enabled()
    user = step.principal.user
    try:
        target = await es.load(user, body.validation_id)
    except MeterValidationExpiredError:
        again = await ps.find_by_key(user, idempotency_key)   # a replay must still return the original purchase
        if again is None:
            raise
        return ok(public_view(again, await db.get(ElectricityOrder, again.id)), "Your request has been received.")
    txn = await ps.create_electricity(user, target, body.amount_kobo, body.confirmed_price_kobo, idempotency_key,
                                      step.jti, step.expires_at)
    if txn.status == "PENDING":
        try:
            request.app.state.dispatcher.enqueue_execute(txn.id)
        except Exception:  # noqa: BLE001  the sweeper picks it up
            pass
    return ok(public_view(txn, await db.get(ElectricityOrder, txn.id)), "Your request has been received.")


@router.get("/{reference}/token")
async def token(reference: Annotated[str, Path(pattern=r"^txn_[0-9a-f]{32}$")], p: Principal = Depends(current_principal),
                db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
                settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    """The only place a token is ever returned. Owner-only, rate-limited, audited, never cached."""
    await ratelimit.hit(redis, f"rl:token:{p.user.id}", 30, 3600)
    from sqlalchemy import select
    row = (await db.execute(select(Transaction, ElectricityOrder).join(
        ElectricityOrder, ElectricityOrder.transaction_id == Transaction.id).where(
        Transaction.reference == reference, Transaction.user_id == p.user.id))).first()
    if row is None or row[0].status != "SUCCESSFUL" or row[1].token_status != "DELIVERED" or not row[1].token_ciphertext:
        raise NotFoundError("No token is available for this transaction.")
    txn, order = row
    value = decrypt(settings.encryption_key.get_secret_value(), order.token_ciphertext, txn.reference)
    audit.record(db, action="token.viewed", actor_user_id=p.user.id, resource_type="transaction", resource_id=txn.reference)
    await db.commit()
    return ok({"token": value, "units": order.units, "meter_number": mask(order.meter_number), "disco": order.disco_name})
