import logging
from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

redis_client: Redis = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=0.2,
    socket_timeout=0.5,
    retry_on_timeout=False,
)


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency yielding the shared Redis client."""
    yield redis_client


async def check_redis_connection() -> bool:
    """Used by the health endpoint. Never raises — returns False on any failure."""
    try:
        return await redis_client.ping()
    except Exception:
        logger.warning("Redis connectivity check failed", exc_info=True)
        return False
