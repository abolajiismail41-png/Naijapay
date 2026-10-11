import json
import logging
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
from app.modules.electricity.models import ElectricityDisco
from app.modules.providers.base import BillProvider
from app.modules.providers.errors import MeterInvalidError, ProviderUnavailableError
from app.modules.providers.prices import electricity_price, is_fresh
from app.modules.services.errors import PricingUnavailableError
from app.modules.transactions.purchase import PROVIDER, MeterTarget
from app.modules.transactions.views import mask
from app.modules.users.models import User

log = logging.getLogger(__name__)
METER_TYPES = ("PREPAID", "POSTPAID")


class ElectricityDisabledError(AppError):
    status_code, code = 503, "service_unavailable"
    user_message = "Electricity purchases are temporarily unavailable. Please try again later."


class DiscoUnavailableError(AppError):
    status_code, code = 404, "disco_unavailable"
    user_message = "This electricity provider is not available."


class MeterValidationExpiredError(AppError):
    status_code, code = 409, "meter_validation_expired"
    user_message = "Please verify the meter number again before paying."


class ElectricityService:
    def __init__(self, db: AsyncSession, redis: Redis, settings: Settings, providers: dict[str, BillProvider]) -> None:
        self.db, self.redis, self.settings, self.providers = db, redis, settings, providers

    def check_enabled(self) -> None:
        """Fail safe: the live Inlomax adapter stays off until it has been verified against their sandbox."""
        if self.settings.bill_provider == "inlomax" and not self.settings.inlomax_electricity_enabled:
            raise ElectricityDisabledError()

    async def listed_discos(self) -> list[tuple[ElectricityDisco, list[str]]]:
        out = []
        discos = (await self.db.execute(select(ElectricityDisco).where(
            ElectricityDisco.listed.is_(True), ElectricityDisco.active.is_(True), ElectricityDisco.provider_code == PROVIDER)
            .order_by(ElectricityDisco.sort_order, ElectricityDisco.name))).scalars()
        for d in discos:
            types = []
            for t in METER_TYPES:
                sid = d.service_id(t)
                row = await electricity_price(self.db, PROVIDER, sid) if sid else None
                if row is not None and is_fresh(row, self.settings.provider_cost_max_age_h):
                    types.append(t)
            if types:
                out.append((d, types))
        return out

    async def validate(self, user: User, disco_id: uuid.UUID, meter_type: str, meter_number: str) -> tuple[str, MeterTarget]:
        self.check_enabled()
        await ratelimit.hit(self.redis, f"rl:meter:{user.id}", 10, 3600)      # meter lookups reveal holder names
        await ratelimit.hit(self.redis, f"rl:meter:day:{user.id}", 40, 86400)
        disco = await self.db.get(ElectricityDisco, disco_id)
        sid = disco.service_id(meter_type) if disco and disco.listed and disco.active else None
        if disco is None or not sid:
            raise DiscoUnavailableError()
        row = await electricity_price(self.db, PROVIDER, sid)
        if row is None or not is_fresh(row, self.settings.provider_cost_max_age_h):
            raise PricingUnavailableError(reason="no fresh provider cost", service=sid)
        breaker = CircuitBreaker(self.redis, "provider:inlomax:validate")
        if await breaker.is_open():
            raise ProviderUnavailableError()
        try:
            info = await self.providers[PROVIDER].validate_meter(disco.provider_disco_code, sid, meter_number, meter_type)
        except ProviderUnavailableError:
            await breaker.record_failure()
            raise
        except MeterInvalidError:
            await breaker.record_success()   # the provider answered; the meter is simply wrong
            audit.record(self.db, action="meter.validation_failed", actor_user_id=user.id,
                         meta={"disco": disco.code, "meter": mask(meter_number)})
            await self.db.commit()
            raise
        await breaker.record_success()
        target = MeterTarget(disco.id, disco.code, disco.name, disco.provider_disco_code, meter_type, meter_number,
                             info.customer_name, info.address, sid, info.min_amount.kobo if info.min_amount else 0)
        vid = uuid.uuid4().hex
        await self.redis.set(f"meter:val:{vid}", json.dumps({"user_id": str(user.id), **asdict(target), "disco_id": str(disco.id)}),
                             ex=self.settings.meter_validation_ttl_s)
        audit.record(self.db, action="meter.validated", actor_user_id=user.id, meta={"disco": disco.code, "meter": mask(meter_number)})
        await self.db.commit()
        return vid, target

    async def load(self, user: User, validation_id: str) -> MeterTarget:
        raw = await self.redis.get(f"meter:val:{validation_id}")
        if not raw:
            raise MeterValidationExpiredError()
        data: dict[str, Any] = json.loads(raw)
        if data.pop("user_id") != str(user.id):    # a validation is private to the user who made it
            raise MeterValidationExpiredError()
        data["disco_id"] = uuid.UUID(data["disco_id"])
        return MeterTarget(**data)
