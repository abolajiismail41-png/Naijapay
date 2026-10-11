import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, ok
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.reconciliation.models import ReconciliationRecord, ReconciliationRun
from app.modules.reconciliation.service import run_internal_reconciliation

router = APIRouter(prefix="/api/v1/admin/reconciliation", tags=["admin-reconciliation"])


@router.post("/run")
async def run_now(principal: Principal = Depends(require_permission(Permission.RECONCILIATION_RUN)),
                  db: AsyncSession = Depends(get_db)):
    return ok(await run_internal_reconciliation(db, actor_user_id=principal.user.id), "Internal reconciliation completed.")


@router.get("")
async def list_runs(status: Literal["RUNNING", "CLEAN", "ISSUES", "FAILED"] | None = None,
                    limit: int = Query(30, ge=1, le=100),
                    _: Principal = Depends(require_permission(Permission.RECONCILIATION_RUN)),
                    db: AsyncSession = Depends(get_db)):
    stmt = select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc()).limit(limit)
    if status: stmt = stmt.where(ReconciliationRun.status == status)
    rows = list((await db.execute(stmt)).scalars())
    return ok({"items": [{"id": str(r.id), "run_type": r.run_type, "status": r.status,
        "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "summary": r.summary} for r in rows]})


@router.get("/{run_id}/records")
async def run_records(run_id: uuid.UUID, limit: int = Query(100, ge=1, le=500),
                      _: Principal = Depends(require_permission(Permission.RECONCILIATION_RUN)),
                      db: AsyncSession = Depends(get_db)):
    run = await db.get(ReconciliationRun, run_id)
    if run is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("Reconciliation run not found.")
    rows = list((await db.execute(select(ReconciliationRecord).where(ReconciliationRecord.run_id == run_id)
                                  .order_by(ReconciliationRecord.id).limit(limit))).scalars())
    return ok({"items": [{"id": str(r.id), "code": r.code, "entity_type": r.entity_type,
        "entity_id": r.entity_id, "classification": r.classification, "detail": r.detail,
        "created_at": r.created_at.isoformat()} for r in rows]})
