from redis.asyncio import Redis


async def invalidate_prefix(redis: Redis, prefix: str) -> None:
    """Best-effort: public catalogue caches are short-lived and every purchase re-confirms the price anyway."""
    try:
        async for key in redis.scan_iter(match=f"{prefix}*", count=100):
            await redis.delete(key)
    except Exception:  # noqa: BLE001
        pass
