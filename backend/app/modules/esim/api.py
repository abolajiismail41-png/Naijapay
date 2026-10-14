from typing import Any
from fastapi import APIRouter, Depends
from app.core.deps import ok
from app.core.errors import ServiceUnavailableError
from app.modules.auth.deps import Principal, current_principal

router = APIRouter(prefix="/api/v1/esim", tags=["esim"])

@router.get("/status")
async def status(_: Principal = Depends(current_principal)) -> dict[str, Any]:
    # No catalogue, order, provisioning, QR or top-up API is implemented until SMS-Man confirms one.
    return ok({"enabled": False, "available": False, "reason": "The official SMS-Man eSIM API has not been verified."})

@router.get("/plans")
async def plans(_: Principal = Depends(current_principal)) -> dict[str, Any]:
    raise ServiceUnavailableError("eSIM plans are not available yet because an official provider API has not been verified.")

@router.get("/orders")
async def orders(_: Principal = Depends(current_principal)) -> dict[str, Any]:
    return ok([])

@router.post("/orders")
async def purchase(_: Principal = Depends(current_principal)) -> dict[str, Any]:
    raise ServiceUnavailableError("eSIM purchasing is disabled until the official provider API is verified.")
