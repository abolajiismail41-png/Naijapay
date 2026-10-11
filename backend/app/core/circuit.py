from redis.asyncio import Redis


class CircuitBreaker:
    """Shared across API and worker processes via Redis. Opens after repeated unknown-outcome failures."""

    def __init__(self, redis: Redis, name: str, *, threshold: int = 5, window_s: int = 60, open_s: int = 30) -> None:
        self._r, self._fails, self._open = redis, f"cb:{name}:fails", f"cb:{name}:open"
        self._threshold, self._window, self._open_s = threshold, window_s, open_s

    async def is_open(self) -> bool:
        return bool(await self._r.exists(self._open))

    async def record_failure(self) -> None:
        n = await self._r.incr(self._fails)
        if n == 1:
            await self._r.expire(self._fails, self._window)
        if n >= self._threshold:
            await self._r.set(self._open, 1, ex=self._open_s)
            await self._r.delete(self._fails)

    async def record_success(self) -> None:
        await self._r.delete(self._fails)
