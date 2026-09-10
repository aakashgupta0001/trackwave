from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.cache.redis import check_redis_connection
from app.core.config import get_settings
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


class DependencyStatus(BaseModel):
    database: str
    redis: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    timestamp: datetime
    dependencies: DependencyStatus


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness/readiness probe. Always returns 200 — `status` reflects dependency health
    so orchestrators and the frontend can distinguish "up" from "up but degraded" without
    the endpoint itself flapping.
    """
    settings = get_settings()

    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    return HealthResponse(
        status="ok" if db_ok and redis_ok else "degraded",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        dependencies=DependencyStatus(
            database="up" if db_ok else "down",
            redis="up" if redis_ok else "down",
        ),
    )
