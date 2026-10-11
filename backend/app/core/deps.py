from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    # Use cases commit explicitly so the response is never sent before the commit.
    async with request.app.state.session_factory() as session:
        yield session


def get_redis(request: Request) -> Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def client_ip(request: Request) -> str:
    # Behind a load balancer run uvicorn with --proxy-headers and a trusted forwarded-allow-ips.
    return request.client.host if request.client else "unknown"


def ok(data: Any = None, message: str = "") -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return {"success": True, "data": data, "message": message}
