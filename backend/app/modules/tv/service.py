import json
import uuid
from dataclasses import asdict
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.circuit import CircuitBreaker
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.audit import service as audit
from app.modules.providers.base import BillProvider, TVCustomerInfo
from app.modules.providers.errors import ProviderUnavailableError, SmartcardInvalidError
from app.modules.providers.prices import tv_price, is_fresh
from app.modules.services.errors import PricingUnavailableError
from app.modules.transactions.purchase import PROVIDER, TVTarget
from app.modules.transactions.views import mask
from app.modules.tv.models import TVProduct
from app.modules.users.models import User


class TVDisabledError(AppError):
    status_code, code = 503, "service_unavailable"
    user_message = "TV subscriptions are temporarily unavailable. Please try again later."


class TVOperatorUnavailableError(AppError):
    status_code, code = 404, "tv_operator_unavailable"
    user_message = "This TV provider is not available."


class TVValidationExpiredError(AppError):
    status_code, code = 409, "tv_validation_expired"
    user_message = "Please verify the smartcard number again before paying."


class TVService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings, providers: dict[str, BillProvider]) -> None:
        self.db, self.redis, self.settings, self.providers = db, redis, settings, providers

    def check_enabled(self) -> None:
        if self.settings.bill_provider == "inlomax" and not self.settings.inlomax_tv_enabled:
            raise TVDisabledError()

    async def operators(self) -> list[dict[str, str]]:
        self.check_enabled()
        rows = (await self.db.execute(select(TVProduct.operator_code, TVProduct.operator_name).where(
            TVProduct.provider_code == PROVIDER, TVProduct.active.is_(True), TVProduct.listed.is_(True))
            .distinct().order_by(TVProduct.operator_name))).all()
        out = []
        for code, name in rows:
            products = (await self.db.execute(select(TVProduct).where(
                TVProduct.provider_code == PROVIDER, TVProduct.operator_code == code,
                TVProduct.active.is_(True), TVProduct.listed.is_(True)))).scalars().all()
            sellable = False
            for product in products:
                cost = await tv_price(self.db, PROVIDER, product.provider_service_id)
                if cost is not None and is_fresh(cost, self.settings.provider_cost_max_age_h):
                    sellable = True
                    break
            if sellable:
                out.append({"code": code, "name": name})
        return out

    async def validate(self, user: User, operator_code: str, smartcard_number: str) -> tuple[str, TVCustomerInfo, str]:
        self.check_enabled()
        await ratelimit.hit(self.redis, f"rl:tv-validate:{user.id}", 10, 3600)
        await ratelimit.hit(self.redis, f"rl:tv-validate:day:{user.id}", 40, 86400)
        products = (await self.db.execute(select(TVProduct).where(
            TVProduct.provider_code == PROVIDER, TVProduct.operator_code == operator_code,
            TVProduct.listed.is_(True), TVProduct.active.is_(True)).order_by(TVProduct.sort_order))).scalars().all()
        if not products:
            raise TVOperatorUnavailableError()
        # Do not guess operator IDs: all sellable bouquets for an operator must agree.
        operator_ids = {p.provider_operator_id for p in products}
        if len(operator_ids) != 1:
            raise TVDisabledError()
        breaker = CircuitBreaker(self.redis, f"provider:{PROVIDER}:tv-validate")
        if await breaker.is_open():
            raise ProviderUnavailableError()
        try:
            info = await self.providers[PROVIDER].validate_smartcard(next(iter(operator_ids)), smartcard_number)
        except ProviderUnavailableError:
            await breaker.record_failure()
            raise
        except SmartcardInvalidError:
            await breaker.record_success()
            audit.record(self.db, action="tv.validation_failed", actor_user_id=user.id,
                         meta={"operator": operator_code, "smartcard": mask(smartcard_number)})
            await self.db.commit()
            raise
        await breaker.record_success()
        target = {"user_id": str(user.id), "operator_code": operator_code,
                  "operator_name": products[0].operator_name, "smartcard_number": smartcard_number,
                  "customer_name": info.customer_name, "current_bouquet": info.current_bouquet}
        vid = uuid.uuid4().hex
        await self.redis.set(f"tv:val:{vid}", json.dumps(target), ex=self.settings.meter_validation_ttl_s)
        audit.record(self.db, action="tv.smartcard_validated", actor_user_id=user.id,
                     meta={"operator": operator_code, "smartcard": mask(smartcard_number)})
        await self.db.commit()
        return vid, info, products[0].operator_name

    async def load_target(self, user: User, validation_id: str, product: TVProduct) -> TVTarget:
        raw = await self.redis.get(f"tv:val:{validation_id}")
        if not raw:
            raise TVValidationExpiredError()
        data: dict[str, Any] = json.loads(raw)
        if data.get("user_id") != str(user.id) or data.get("operator_code") != product.operator_code:
            raise TVValidationExpiredError()
        return TVTarget(product.id, data["operator_code"], data["operator_name"], data["smartcard_number"],
                        data["customer_name"], data.get("current_bouquet", ""), product.provider_service_id, product.name)
