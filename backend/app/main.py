import asyncio
from contextlib import asynccontextmanager
import logging
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.correlation import CorrelationIdMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.routes import eta, health, live, network, providers, stations, system, trains, websocket
from app.cache.redis import redis_client
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import engine, get_db
from app.monitoring.metrics import generate_prometheus_metrics
from app.workers.ingestion_worker import ingestion_worker

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Background ingestion worker (opt-in)
    if settings.LIVE_INGESTION_ENABLED:
        ingestion_worker.start()
    yield
    # Graceful shutdown: stop workers and close connection pools
    await ingestion_worker.stop()
    try:
        await redis_client.aclose()
    except Exception:
        pass
    try:
        await engine.dispose()
    except Exception:
        pass
    logger.info("RAILCAST graceful shutdown completed")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Real-Time AI-Powered ETA & Railway Network Intelligence Platform",
    lifespan=lifespan,
)

# Core Middleware Pipeline
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(health.router)
app.include_router(trains.router, prefix=settings.API_V1_PREFIX)
app.include_router(stations.router, prefix=settings.API_V1_PREFIX)
app.include_router(live.router, prefix=settings.API_V1_PREFIX)
app.include_router(providers.router, prefix=settings.API_V1_PREFIX)
app.include_router(eta.router, prefix=settings.API_V1_PREFIX)
app.include_router(network.router, prefix=settings.API_V1_PREFIX)
app.include_router(system.router, prefix=settings.API_V1_PREFIX)
app.include_router(system.router)
app.include_router(websocket.router)
app.include_router(websocket.router, prefix=settings.API_V1_PREFIX)


@app.get("/metrics", tags=["monitoring"], summary="Prometheus metrics exporter")
async def prometheus_metrics(session: AsyncSession = Depends(get_db)) -> Response:
    """Standard Prometheus metrics exposition format for platform scrapers."""
    content = await generate_prometheus_metrics(session)
    return Response(content=content, media_type="text/plain; version=0.0.4; charset=utf-8")


from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    req_id = getattr(request.state, "request_id", None)
    error_code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(exc.status_code, "HTTP_ERROR")

    msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error": {
                "code": error_code,
                "message": msg,
                "details": exc.detail if isinstance(exc.detail, (dict, list)) else {},
                "request_id": req_id,
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    req_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request payload or parameters.",
                "details": exc.errors(),
                "request_id": req_id,
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler so unexpected errors never leak stack traces to clients."""
    req_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception on %s %s [request_id=%s]",
        request.method,
        request.url.path,
        req_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "details": {},
                "request_id": req_id,
            },
        },
    )


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {"service": settings.PROJECT_NAME, "status": "running", "docs": "/docs"}
