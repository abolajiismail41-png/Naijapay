import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.modules.payments.processors import build_processor
from app.modules.payments.processors.base import PaymentProcessor
from app.modules.providers import build_bill_providers
from app.modules.providers.base import BillProvider

T = TypeVar("T")


@dataclass
class Runtime:
    db: AsyncSession
    redis: Redis
    settings: Settings
    processor: PaymentProcessor
    providers: dict[str, BillProvider]
    http: httpx.AsyncClient


async def _run(job: Callable[[Runtime], Awaitable[T]]) -> T:
    settings = get_settings()
    engine = make_engine(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    try:
        async with make_session_factory(engine)() as db:
            return await job(Runtime(db, redis, settings, build_processor(settings, client),
                                     build_bill_providers(settings, client), client))
    finally:
        await client.aclose()
        await redis.aclose()
        await engine.dispose()


def run_job(job: Callable[[Runtime], Awaitable[T]]) -> T:
    """Celery tasks are sync; each runs its async job on a fresh loop with its own pools."""
    return asyncio.run(_run(job))
