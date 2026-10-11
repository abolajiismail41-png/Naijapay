import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.core.errors import NotFoundError
from app.modules.auth.deps import Principal, current_principal
from app.modules.transactions.models import Transaction
from app.modules.transactions.queries import order_of, with_orders
from app.modules.transactions.views import public_view

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(limit: int = Query(20, ge=1, le=100), cursor: uuid.UUID | None = None,
                            p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = with_orders().where(Transaction.user_id == p.user.id)
    if cursor:
        q = q.where(Transaction.id < cursor)
    rows = (await db.execute(q.order_by(Transaction.id.desc()).limit(limit + 1))).all()
    return ok({"items": [public_view(r[0], order_of(r)) for r in rows[:limit]],
               "next_cursor": str(rows[limit - 1][0].id) if len(rows) > limit else None})


@router.get("/{reference}")
async def get_transaction(reference: Annotated[str, Path(pattern=r"^txn_[0-9a-f]{32}$")],
                          p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (await db.execute(with_orders().where(Transaction.reference == reference, Transaction.user_id == p.user.id))).first()
    if row is None:
        raise NotFoundError("Transaction not found.")
    return ok(public_view(row[0], order_of(row)))
