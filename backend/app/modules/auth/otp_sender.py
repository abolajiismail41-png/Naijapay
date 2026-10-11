from typing import Protocol

from redis.asyncio import Redis

from app.core.config import Environment, Settings
from app.core.errors import ServiceUnavailableError


class OtpSender(Protocol):
    async def send(self, phone: str, code: str, purpose: str) -> None: ...


class DevRedisOtpSender:
    """Local/test only: parks the code in Redis so developers and tests can read it. Never logs it."""

    def __init__(self, redis: Redis, ttl_s: int) -> None:
        self._redis, self._ttl = redis, ttl_s

    async def send(self, phone: str, code: str, purpose: str) -> None:
        await self._redis.set(f"dev:otp:{phone}", code, ex=self._ttl)


class UnconfiguredOtpSender:
    async def send(self, phone: str, code: str, purpose: str) -> None:
        raise ServiceUnavailableError("We could not send a verification code right now.")


def build_otp_sender(settings: Settings, redis: Redis) -> OtpSender:
    if settings.environment in (Environment.LOCAL, Environment.TEST):
        return DevRedisOtpSender(redis, settings.otp_ttl_min * 60)
    return UnconfiguredOtpSender()  # replaced by the SMS adapter in Phase 10
