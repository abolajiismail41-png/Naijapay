from redis.asyncio import Redis

from app.core.errors import RateLimitedError


async def hit(redis: Redis, key: str, limit: int, window_s: int) -> None:
    """Fixed-window counter. SET NX EX guarantees the key always has a TTL."""
    await redis.set(key, 0, ex=window_s, nx=True)
    count = await redis.incr(key)
    if count > limit:
        ttl = await redis.ttl(key)
        err = RateLimitedError()
        err.headers = {"Retry-After": str(max(ttl, 1))}
        raise err
