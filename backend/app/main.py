from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
from redis.asyncio import Redis

from app.core.config import Environment, Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.modules.admin.api import router as finance_router
from app.modules.admin.operations import router as admin_operations_router
from app.modules.airtime.api import router as airtime_router
from app.modules.auth.api import router as auth_router
from app.modules.data.admin_api import router as data_admin_router
from app.modules.data.api import router as data_router
from app.modules.education.admin_api import router as education_admin_router
from app.modules.education.api import router as education_router
from app.modules.electricity.admin_api import router as electricity_admin_router
from app.modules.electricity.api import router as electricity_router
from app.modules.health.api import router as health_router
from app.modules.payments.api import router as funding_router
from app.modules.payments.dispatch import CeleryDispatcher
from app.modules.payments.processors import build_processor
from app.modules.payments.webhooks import router as webhook_router
from app.modules.providers import build_bill_providers
from app.modules.services.admin_api import router as pricing_admin_router
from app.modules.transactions.admin_api import router as txn_admin_router
from app.modules.transactions.api import router as txn_router
from app.modules.transactions.webhooks import router as provider_webhook_router
from app.modules.tv.api import router as tv_router
from app.modules.tv.admin_api import router as tv_admin_router
from app.modules.notifications.api import router as notifications_router
from app.modules.referrals.api import router as referrals_router
from app.modules.promotions.api import router as promotions_router, admin as promotions_admin_router
from app.modules.users.api import router as users_router
from app.modules.wallet.api import router as wallet_router
from app.modules.fraud.api import router as fraud_router
from app.modules.reconciliation.api import router as reconciliation_router
from app.modules.virtual_numbers.api import router as virtual_numbers_router, admin_router as virtual_numbers_admin_router
from app.modules.esim.api import router as esim_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings)
        app.state.session_factory = make_session_factory(app.state.engine)
        app.state.redis = Redis.from_url(settings.redis_url, socket_timeout=2, decode_responses=True)
        app.state.http = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))
        app.state.payment_processor = build_processor(settings, app.state.http)
        app.state.bill_providers = build_bill_providers(settings, app.state.http)
        app.state.dispatcher = CeleryDispatcher()
        try:
            yield
        finally:
            await app.state.http.aclose()
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware, max_request_bytes=settings.max_request_bytes)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(wallet_router)
    app.include_router(funding_router)
    app.include_router(webhook_router)
    app.include_router(provider_webhook_router)
    app.include_router(airtime_router)
    app.include_router(data_router)
    app.include_router(data_admin_router)
    app.include_router(electricity_router)
    app.include_router(electricity_admin_router)
    app.include_router(education_router)
    app.include_router(education_admin_router)
    app.include_router(tv_router)
    app.include_router(tv_admin_router)
    app.include_router(notifications_router)
    app.include_router(referrals_router)
    app.include_router(promotions_router)
    app.include_router(promotions_admin_router)
    app.include_router(txn_router)
    app.include_router(txn_admin_router)
    app.include_router(pricing_admin_router)
    app.include_router(finance_router)
    app.include_router(admin_operations_router)
    app.include_router(fraud_router)
    app.include_router(reconciliation_router)
    app.include_router(virtual_numbers_router)
    app.include_router(virtual_numbers_admin_router)
    app.include_router(esim_router)
    if settings.environment is Environment.LOCAL and settings.payment_processor == "sandbox":
        from app.modules.payments.dev_api import router as dev_router
        app.include_router(dev_router)  # local sandbox helper, never mounted elsewhere
    return app


app = create_app()
