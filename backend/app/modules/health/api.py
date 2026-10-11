import asyncio

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter(tags=["health"])
_CHECK_TIMEOUT_S = 2.0


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _db_ok(request: Request) -> bool:
    try:
        async with request.app.state.engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), _CHECK_TIMEOUT_S)
        return True
    except Exception:
        return False


async def _redis_ok(request: Request) -> bool:
    try:
        return bool(await asyncio.wait_for(request.app.state.redis.ping(), _CHECK_TIMEOUT_S))
    except Exception:
        return False


@router.get("/health/ready")
async def ready(request: Request, response: Response) -> dict[str, str]:
    db, redis = await asyncio.gather(_db_ok(request), _redis_ok(request))
    if not (db and redis):
        response.status_code = 503
    # Booleans only: no hostnames, versions, or error text on a public endpoint.
    return {"status": "ok" if db and redis else "degraded",
            "database": "up" if db else "down", "redis": "up" if redis else "down"}
