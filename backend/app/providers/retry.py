import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Retries `fn` with exponential backoff (0.5s, 1s, 2s, ...) on any exception in
    `retry_on`. Re-raises the last exception once attempts are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except retry_on as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "retry attempt=%d/%d delay_seconds=%.1f error=%s", attempt, max_attempts, delay, exc
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
