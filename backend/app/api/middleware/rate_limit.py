"""In-memory sliding window rate limiting middleware for API abuse protection."""

from collections import defaultdict, deque
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects public endpoints from excessive requests using a client IP sliding window."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Do not rate limit system liveness / metrics or WebSocket upgrades
        path = request.url.path
        if path.startswith("/api/v1/system/liveness") or path == "/metrics" or path.startswith("/ws"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = 60.0  # 1 minute window
        max_requests = settings.RATE_LIMIT_REQUESTS_PER_MINUTE

        queue = self._requests[client_ip]

        # Purge entries older than window
        while queue and queue[0] < now - window:
            queue.popleft()

        if len(queue) >= max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit of {max_requests} requests per minute exceeded. Please retry later.",
                    }
                },
                headers={"Retry-After": "60"},
            )

        queue.append(now)
        return await call_next(request)
