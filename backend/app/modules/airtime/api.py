from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.money import Money
from app.core.phone import Phone
from app.modules.auth.deps import PinStepUp, Principal, current_principal, require_pin_step_up
from app.modules.transactions.models import AirtimeOrder
from app.modules.transactions.purchase import NETWORKS, PurchaseService
from app.modules.transactions.views import public_view

router = APIRouter(prefix="/api/v1/airtime", tags=["airtime"])
Network = Literal["MTN", "AIRTEL", "GLO", "9MOBILE"]
Amount = Annotated[int, Field(strict=True, gt=0)]
IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")]


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network: Network
    amount_kobo: Amount


class BuyIn(QuoteIn):
    phone: Phone
    confirmed_price_kobo: Amount  # the price the customer saw; if it changed we stop and ask again
    confirm_network: bool = False  # customer confirmed a number whose prefix looks like another network


def _svc(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
         settings: Settings = Depends(get_app_settings)) -> PurchaseService:
    return PurchaseService(db, redis, settings)


@router.get("/networks")
async def networks(_: Principal = Depends(current_principal), settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    return ok([{"network": n, "min_kobo": settings.airtime_min_kobo, "max_kobo": settings.airtime_max_kobo} for n in NETWORKS])


@router.post("/quote")
async def quote(body: QuoteIn, _: Principal = Depends(current_principal),
                svc: PurchaseService = Depends(_svc)) -> dict[str, Any]:
    b, _rule, _row = await svc.quote_airtime(body.network, body.amount_kobo)
    price = b.customer_price   # the only money figure a customer ever receives
    return ok({"network": body.network, "amount_kobo": body.amount_kobo, "amount": Money(body.amount_kobo).naira_str(),
               "price_kobo": price.kobo, "price": price.naira_str()})


@router.post("", status_code=202)
async def buy(body: BuyIn, request: Request, idempotency_key: IdemKey, step: PinStepUp = Depends(require_pin_step_up),
              svc: PurchaseService = Depends(_svc), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    txn = await svc.create_airtime(step.principal.user, body.network, body.phone, body.amount_kobo,
                                   body.confirmed_price_kobo, idempotency_key, step.jti, step.expires_at, body.confirm_network)
    if txn.status == "PENDING":
        try:  # best effort: the sweeper picks up anything that is not enqueued
            request.app.state.dispatcher.enqueue_execute(txn.id)
        except Exception:  # noqa: BLE001
            pass
    order = await db.get(AirtimeOrder, txn.id)
    return ok(public_view(txn, order), "Your request has been received.")
