from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_app_settings, get_db, get_redis, ok
from app.core.errors import ConflictError, NotFoundError
from app.core.money import Money
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission, has_permission
from app.modules.services.models import PricingSnapshot
from app.modules.transactions.execution import TransactionService
from app.modules.transactions.models import Transaction, TransactionEvent
from app.modules.transactions.queries import order_of, with_orders
from app.modules.transactions.views import public_view

router = APIRouter(
    prefix="/api/v1/admin/transactions",
    tags=["admin-transactions"],
)

Ref = Annotated[str, Path(pattern=r"^txn_[0-9a-f]{32}$")]


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["SUCCESS", "FAILED"]
    note: str = Field(min_length=5, max_length=200)
    provider_cost_kobo: Annotated[int, Field(strict=True, gt=0)] | None = None
    provider_reference: str | None = Field(default=None, max_length=80)
    token: str | None = Field(default=None, max_length=200)
    pins: list[tuple[str, str]] | None = Field(default=None, max_length=20)


@router.get("/{reference}")
async def detail(
    reference: Ref,
    p: Principal = Depends(
        require_permission(Permission.TRANSACTIONS_READ)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            with_orders().where(Transaction.reference == reference)
        )
    ).first()

    if row is None:
        raise NotFoundError("Transaction not found.")

    transaction, order = row[0], order_of(row)

    events = (
        await db.execute(
            select(TransactionEvent)
            .where(TransactionEvent.transaction_id == transaction.id)
            .order_by(TransactionEvent.id)
        )
    ).scalars().all()

    out = public_view(transaction, order) | {
        "user_id": str(transaction.user_id),
        "provider_reference": transaction.provider_reference,
        "failure_reason": transaction.failure_reason,
        "events": [
            {
                "from": event.from_status,
                "to": event.to_status,
                "note": event.note,
                "at": (
                    event.created_at.isoformat()
                    if event.created_at
                    else None
                ),
            }
            for event in events
        ],
    }

    # Support users without finance permission must not see cost or margin.
    if has_permission(p.user.role, Permission.FINANCE_PROFIT_READ):
        snapshot = await db.get(PricingSnapshot, transaction.id)

        if snapshot:
            pricing_fields = (
                "cost",
                "markup",
                "fee",
                "list_price",
                "discount",
                "customer_price",
                "referral_commission",
                "processing_cost",
                "gross_profit_before_discount",
                "gross_profit",
                "net_contribution",
            )

            pricing = {
                field: Money(
                    getattr(snapshot, f"{field}_kobo")
                ).naira_str()
                for field in pricing_fields
            }

            pricing.update(
                {
                    "margin_pct": str(snapshot.margin_pct),
                    "rule_version": snapshot.rule_version,
                    "capped": snapshot.capped,
                    "subsidized": snapshot.subsidized,
                    "actual_provider_cost": (
                        Money(transaction.provider_cost_kobo).naira_str()
                        if transaction.provider_cost_kobo is not None
                        else None
                    ),
                }
            )

            out["pricing"] = pricing

    return ok(out)


@router.post("/{reference}/resolve")
async def resolve(
    reference: Ref,
    body: ResolveIn,
    request: Request,
    p: Principal = Depends(
        require_permission(Permission.TRANSACTIONS_RESOLVE)
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, Any]:
    svc = TransactionService(
        db,
        redis,
        settings,
        request.app.state.bill_providers,
    )
    existing = (await db.execute(select(Transaction).where(Transaction.reference == reference))).scalar_one_or_none()
    if existing is not None and existing.service_type == "VNUMBER":
        raise ConflictError("Virtual number orders must be reconciled from Virtual Numbers administration with provider evidence.")

    transaction = await svc.resolve_manually(
        reference,
        actor_id=p.user.id,
        outcome=body.outcome,
        note=body.note,
        cost_kobo=body.provider_cost_kobo,
        provider_reference=body.provider_reference,
        token=body.token,
        pins=body.pins,
    )

    return ok(
        {
            "reference": transaction.reference,
            "status": transaction.status,
        },
        "Transaction resolved.",
    )