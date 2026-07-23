import asyncio

import redis.asyncio as aioredis
from redis.asyncio import Redis

from drop.config import get_settings

_redis_client: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis_client() -> Redis:
    global _redis_client, _redis_loop

    try:
        current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _redis_client is None or _redis_loop != current_loop:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        _redis_loop = current_loop

    return _redis_client


async def close_redis_client() -> None:
    global _redis_client, _redis_loop
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        _redis_loop = None
