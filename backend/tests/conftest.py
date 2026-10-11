import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")


# ---------- integration fixtures (need Postgres + Redis; skipped when unreachable) ----------
import asyncio  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from fastapi import APIRouter, Depends  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

import app.models_registry  # noqa: E402,F401
from app.core.config import Settings  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.audit.ddl import IMMUTABLE_DDL  # noqa: E402
from app.modules.ledger.accounts import ensure_system_accounts  # noqa: E402
from app.modules.ledger.ddl import LEDGER_DDL  # noqa: E402
from app.modules.services.ddl import PRICING_DDL  # noqa: E402
from app.modules.services.seed import seed_data_statements, seed_education_statements, seed_electricity_statements, seed_statements, seed_tv_statements  # noqa: E402
from app.modules.auth.deps import require_permission  # noqa: E402
from app.modules.auth.rbac import Permission  # noqa: E402


class RecordingDispatcher:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.executes: list[object] = []
        self.provider_events: list[object] = []

    def enqueue_webhook(self, event_id: object) -> None:
        self.events.append(event_id)

    def enqueue_execute(self, txn_id: object) -> None:
        self.executes.append(txn_id)

    def enqueue_provider_webhook(self, event_id: object) -> None:
        self.provider_events.append(event_id)


@dataclass
class Env:
    client: AsyncClient
    redis: Redis
    app: object
    db_url: str


def _test_db_url() -> str:
    base = make_url(os.environ["DATABASE_URL"])
    return base.set(database=f"{base.database}_test").render_as_string(hide_password=False)


async def _ensure_database(url: str) -> None:
    u = make_url(url)
    conn = await asyncpg.connect(
        host=u.host, port=u.port, user=u.username, password=u.password, database="postgres", timeout=3)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", u.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    db_url = _test_db_url()
    redis_url = make_url(os.environ["REDIS_URL"]).set(database="1").render_as_string(hide_password=False)
    redis_url = redis_url.replace("/None", "/1") if "/None" in redis_url else redis_url
    try:
        await _ensure_database(db_url)
        redis = Redis.from_url(redis_url, decode_responses=True)
        await redis.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"integration services unavailable: {exc}")
    await redis.flushdb()
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP FUNCTION IF EXISTS audit_logs_immutable() CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in IMMUTABLE_DDL + LEDGER_DDL + PRICING_DDL:
            await conn.execute(text(stmt))
        await ensure_system_accounts(conn)
        for sql, params in seed_statements() + seed_data_statements() + seed_electricity_statements() + seed_education_statements() + seed_tv_statements():
            await conn.execute(text(sql), params)
    await engine.dispose()

    settings = Settings(_env_file=None, environment="test", database_url=db_url, redis_url=redis_url,
                        jwt_secret="test-jwt-secret", encryption_key="test-encryption-key",
                        webhook_secret="test-webhook-secret", funding_poll_verify_after_s=0,
                        inlomax_webhook_token="test-inlomax-hook-token-1234567890")
    application = create_app(settings)
    probe = APIRouter()

    @probe.get("/_needs_refund_approve")
    async def needs_refund_approve(p=Depends(require_permission(Permission.REFUND_APPROVE))) -> dict[str, str]:
        return {"ok": "yes"}

    application.include_router(probe)
    async with application.router.lifespan_context(application):
        application.state.dispatcher = RecordingDispatcher()
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://t") as client:
            yield Env(client=client, redis=redis, app=application, db_url=db_url)
    await redis.aclose()
