import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import client_ip, get_db, ok
from app.core.errors import ConflictError, NotFoundError
from app.modules.audit import service as audit
from app.modules.auth.deps import Principal, require_permission
from app.modules.auth.rbac import Permission
from app.modules.fraud.models import FraudCase

router = APIRouter(prefix="/api/v1/admin/fraud", tags=["admin-fraud"])


class FraudResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["REVIEWING", "CLEARED", "CONFIRMED"]
    note: str = Field(min_length=5, max_length=300)


@router.get("")
async def list_cases(status: Literal["OPEN", "REVIEWING", "CLEARED", "CONFIRMED"] | None = None,
                     severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
                     limit: int = Query(50, ge=1, le=100),
                     principal: Principal = Depends(require_permission(Permission.FRAUD_REVIEW)),
                     db: AsyncSession = Depends(get_db)):
    stmt = select(FraudCase).order_by(FraudCase.created_at.desc(), FraudCase.id.desc()).limit(limit)
    if status: stmt = stmt.where(FraudCase.status == status)
    if severity: stmt = stmt.where(FraudCase.severity == severity)
    rows = list((await db.execute(stmt)).scalars())
    return ok({"items": [{"id": str(r.id), "transaction_id": str(r.transaction_id), "user_id": str(r.user_id),
        "rule_code": r.rule_code, "severity": r.severity, "score": r.score, "status": r.status,
        "reasons": r.reasons, "resolution_note": r.resolution_note, "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None} for r in rows]})


@router.patch("/{case_id}")
async def resolve_case(case_id: uuid.UUID, body: FraudResolution, request: Request,
                       principal: Principal = Depends(require_permission(Permission.FRAUD_REVIEW)),
                       db: AsyncSession = Depends(get_db)):
    case = (await db.execute(select(FraudCase).where(FraudCase.id == case_id).with_for_update())).scalar_one_or_none()
    if case is None: raise NotFoundError("Fraud case not found.")
    if case.status in ("CLEARED", "CONFIRMED"):
        raise ConflictError("This fraud case is already resolved.")
    before = {"status": case.status}
    case.status = body.status
    case.resolution_note = body.note.strip()
    case.resolved_by_user_id = principal.user.id if body.status in ("CLEARED", "CONFIRMED") else None
    case.resolved_at = datetime.now(timezone.utc) if body.status in ("CLEARED", "CONFIRMED") else None
    audit.record(db, action="fraud.case_updated", actor_user_id=principal.user.id, resource_type="fraud_case",
        resource_id=str(case.id), ip=client_ip(request), before=before,
        after={"status": case.status}, meta={"rule_code": case.rule_code, "note": body.note.strip()})
    await db.commit()
    return ok({"id": str(case.id), "status": case.status, "resolution_note": case.resolution_note}, "Fraud case updated.")
