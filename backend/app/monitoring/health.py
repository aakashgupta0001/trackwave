"""System health, readiness, and liveness check implementations."""

from datetime import datetime, timezone
import logging
from typing import Any

from app.cache.redis import check_redis_connection
from app.core.config import get_settings
from app.db.session import check_database_connection
from app.ml.predictor import ml_predictor
from app.monitoring.schemas import (
    ComponentStatus,
    LivenessResponse,
    OverallSystemStatus,
    ReadinessResponse,
    SystemHealthResponse,
)
from app.providers.manager import provider_manager
from app.streaming.metrics import streaming_metrics

logger = logging.getLogger(__name__)


async def check_system_health() -> SystemHealthResponse:
    """Evaluate deep component health across DB, Redis, Streaming, ML, Provider, and Network."""
    settings = get_settings()

    # 1. Database
    db_ok = await check_database_connection()
    db_status = ComponentStatus.UP if db_ok else ComponentStatus.DOWN

    # 2. Redis
    redis_ok = await check_redis_connection()
    redis_status = ComponentStatus.UP if redis_ok else ComponentStatus.DOWN

    # 3. Streaming worker
    worker_state = streaming_metrics.worker_status
    if not settings.STREAMING_ENABLED:
        streaming_status = ComponentStatus.UNAVAILABLE
    elif worker_state in ("RUNNING", "IDLE", "INITIALIZING"):
        streaming_status = ComponentStatus.UP
    else:
        streaming_status = ComponentStatus.DEGRADED

    # 4. ML Predictor
    model_avail = ml_predictor.is_available()
    model_status = ComponentStatus.UP if model_avail else ComponentStatus.DEGRADED

    # 5. Provider Manager
    try:
        prov_status = await provider_manager.get_status()
        prov_ok = prov_status.primary_provider in ("LIVE", "SIMULATED", "READY")
        provider_status = ComponentStatus.UP if prov_ok else ComponentStatus.DEGRADED
    except Exception:
        provider_status = ComponentStatus.DEGRADED

    # 6. Network Engine
    network_ok = settings.NETWORK_ANALYSIS_ENABLED
    network_status = ComponentStatus.UP if network_ok else ComponentStatus.DEGRADED

    components = {
        "database": db_status.value,
        "redis": redis_status.value,
        "streaming": streaming_status.value,
        "model": model_status.value,
        "provider": provider_status.value,
        "network": network_status.value,
    }

    # Determine overall status
    if db_status == ComponentStatus.DOWN:
        overall = OverallSystemStatus.UNAVAILABLE
    elif any(s in (ComponentStatus.DOWN.value, ComponentStatus.DEGRADED.value) for s in components.values()):
        overall = OverallSystemStatus.DEGRADED
    else:
        overall = OverallSystemStatus.HEALTHY

    details = {
        "active_model_version": ml_predictor.model_version if model_avail else None,
        "environment": settings.ENVIRONMENT,
        "mode": settings.RAILCAST_MODE,
        "worker_status": worker_state,
        "streaming_enabled": settings.STREAMING_ENABLED,
    }

    return SystemHealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc),
        version=settings.VERSION,
        components=components,
        details=details,
    )


async def check_readiness() -> tuple[bool, ReadinessResponse]:
    """Readiness probe: Determines whether the service can accept user traffic.

    Database is required. External providers and ML models are NOT required
    because baseline fallback and cached/simulated providers ensure availability.
    """
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    checks = {
        "database_connected": db_ok,
        "redis_connected": redis_ok,
        "fallback_engine_available": True,
    }

    # Core readiness: service can serve traffic as long as database is up
    ready = db_ok

    return ready, ReadinessResponse(
        ready=ready,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )


def check_liveness() -> LivenessResponse:
    """Ultra-lightweight liveness probe answering 'is process alive?' with zero DB/network I/O."""
    return LivenessResponse(alive=True, timestamp=datetime.now(timezone.utc))
