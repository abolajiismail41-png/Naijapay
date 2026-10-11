import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.money import Money
from app.modules.auth.deps import Principal, current_principal
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.payments.service import FundingService

router = APIRouter(prefix="/api/v1/wallet/funding", tags=["wallet-funding"])

_MESSAGES = {
    PaymentStatus.INITIATED: "We are setting up your payment.",
    PaymentStatus.PENDING: "Complete your payment to fund your wallet.",
    PaymentStatus.SUCCESSFUL: "Payment confirmed. Your wallet has been credited.",
    PaymentStatus.FAILED: "This payment was not successful.",
    PaymentStatus.ABANDONED: "This payment was not completed.",
    PaymentStatus.MISMATCH: "We are reviewing this payment. Your money is safe and our team will resolve it.",
}


class FundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_kobo: int = Field(strict=True, gt=0)  # strict: 5000.5 or "5000" are rejected, never coerced


IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80,
                                pattern=r"^[A-Za-z0-9_\-:.]+$")]


def _svc(request: Request, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
         settings: Settings = Depends(get_app_settings)) -> FundingService:
    return FundingService(db, redis, settings, request.app.state.payment_processor)


def _out(p: Payment) -> dict[str, Any]:
    status = PaymentStatus(p.status)
    return {"reference": p.reference, "status": p.status, "message": _MESSAGES[status],
            "amount_kobo": p.amount_kobo, "amount": Money(p.amount_kobo).naira_str(),
            "fee_kobo": p.fee_kobo, "fee": Money(p.fee_kobo).naira_str(),
            "total_kobo": p.charged_kobo, "total": Money(p.charged_kobo).naira_str(),
            "currency": p.currency,
            "authorization_url": p.authorization_url if status is PaymentStatus.PENDING else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None}


@router.get("/quote")
async def quote(amount_kobo: int = Query(gt=0), _: Principal = Depends(current_principal),
                svc: FundingService = Depends(_svc)) -> dict[str, Any]:
    q = svc.quote(amount_kobo)
    s = svc.settings
    return ok({"amount_kobo": q.amount.kobo, "fee_kobo": q.fee.kobo, "total_kobo": q.total.kobo,
               "amount": q.amount.naira_str(), "fee": q.fee.naira_str(), "total": q.total.naira_str(),
               "min_kobo": s.funding_min_kobo, "max_kobo": s.funding_max_kobo})


@router.post("", status_code=201)
async def start_funding(body: FundIn, idempotency_key: IdemKey, p: Principal = Depends(current_principal),
                        svc: FundingService = Depends(_svc)) -> dict[str, Any]:
    payment = await svc.initiate(p.user, body.amount_kobo, idempotency_key)
    return ok(_out(payment))


@router.get("")
async def list_funding(limit: int = Query(20, ge=1, le=100), cursor: uuid.UUID | None = None,
                       p: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = select(Payment).where(Payment.user_id == p.user.id)
    if cursor:
        q = q.where(Payment.id < cursor)
    rows = list((await db.execute(q.order_by(Payment.id.desc()).limit(limit + 1))).scalars())
    return ok({"items": [_out(r) for r in rows[:limit]],
               "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None})


@router.get("/{reference}")
async def get_funding(reference: Annotated[str, Path(pattern=r"^fnd_[0-9a-f]{32}$")],
                      p: Principal = Depends(current_principal),
                      svc: FundingService = Depends(_svc)) -> dict[str, Any]:
    payment = await svc.get_for_user(p.user.id, reference)
    return ok(_out(await svc.refresh_if_stale(payment)))
