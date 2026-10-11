import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.core.money import CURRENCY, Money
from app.modules.auth.deps import Principal, current_principal
from app.modules.ledger import interface as ledger
from app.modules.wallet.service import WalletService

router = APIRouter(prefix="/api/v1/wallet", tags=["wallet"])


def _naira(m: Money) -> str:
    return f"{m.naira.quantize(Decimal('0.01'))}"  # string, never a float


@router.get("")
async def get_wallet(p: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    wallet = await WalletService(db).get_or_create(p.user.id)
    await db.commit()  # persists the lazily created wallet
    bal = Money(wallet.balance_kobo)
    return ok({"balance_kobo": bal.kobo, "balance": _naira(bal), "currency": CURRENCY,
               "status": wallet.status})


@router.get("/entries")
async def entries(limit: int = Query(20, ge=1, le=100), cursor: uuid.UUID | None = None,
                  p: Principal = Depends(current_principal),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    wallet = await WalletService(db).get_or_create(p.user.id)
    await db.commit()
    rows = await ledger.entries_for_account(db, wallet.ledger_account_id, limit + 1, cursor)
    page = rows[:limit]
    return ok({
        "items": [{"id": str(r.id), "type": "in" if r.direction is ledger.Direction.CREDIT else "out",
                   "amount_kobo": r.amount.kobo, "amount": _naira(r.amount), "kind": r.kind,
                   "description": r.description, "created_at": r.created_at.isoformat()} for r in page],
        "next_cursor": str(page[-1].id) if len(rows) > limit else None,
    })
