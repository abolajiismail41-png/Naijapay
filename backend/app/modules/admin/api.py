from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.modules.admin import profit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission

router = APIRouter(prefix="/api/v1/admin/finance", tags=["admin-finance"])


@router.get("/profit")
async def profit_dashboard(from_date: date | None = None, to_date: date | None = None,
                           group_by: Literal["service", "provider", "network", "date", "disco", "product"] | None = None,
                           _: Principal = Depends(require_permission(Permission.FINANCE_PROFIT_READ)),
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await profit.profit_report(db, from_date, to_date, group_by))


@router.get("/ledger-checks")
async def ledger_checks(_: Principal = Depends(require_permission(Permission.FINANCE_PROFIT_READ)),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    checks = await profit.ledger_checks(db)
    return ok({"all_ok": all(c["ok"] for c in checks), "checks": checks})
