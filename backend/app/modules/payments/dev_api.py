"""LOCAL DEVELOPMENT ONLY. Mounted by main.py only when ENVIRONMENT=local and PAYMENT_PROCESSOR=sandbox."""
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.modules.auth.deps import Principal, current_principal
from app.modules.payments.processors.base import VerifyStatus
from app.modules.payments.service import FundingService

router = APIRouter(prefix="/api/v1/dev", tags=["dev-only"])


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(pattern=r"^fnd_[0-9a-f]{32}$")


@router.post("/sandbox/complete-funding")
async def complete_funding(body: CompleteIn, request: Request, p: Principal = Depends(current_principal),
                           db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis),
                           settings: Settings = Depends(get_app_settings)) -> dict[str, Any]:
    """Pretend the customer paid on the sandbox checkout page, then settle through the normal verified path."""
    svc = FundingService(db, redis, settings, request.app.state.payment_processor)
    payment = await svc.get_for_user(p.user.id, body.reference)
    request.app.state.payment_processor.simulate(payment.processor_reference, status=VerifyStatus.SUCCESS)
    payment = await svc.settle(payment.id, source="dev")
    return ok({"reference": payment.reference, "status": payment.status})
