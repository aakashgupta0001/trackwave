"""Request correlation ID middleware for distributed tracing and structured debugging."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns or propagates an X-Request-ID header on every HTTP request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract existing incoming correlation ID, or generate a fresh UUID
        correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = correlation_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response
