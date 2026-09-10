"""Chaos and failure mode degradation tests for platform resilience."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.ml.exceptions import ModelUnavailableError
from app.ml.predictor import ml_predictor
from app.models.enums import PredictionMode
from app.services.eta_fusion_service import get_final_eta
from app.streaming.consumer import StreamingConsumer


@pytest.mark.asyncio
async def test_failure_mode_redis_down(client: AsyncClient):
    """When Redis is unavailable, health endpoint shows degraded but liveness passes and API functions."""
    with patch("app.monitoring.health.check_redis_connection", AsyncMock(return_value=False)):
        resp_health = await client.get("/api/v1/system/health")
        assert resp_health.status_code == 200
        data = resp_health.json()
        assert data["components"]["redis"] == "DOWN"
        assert data["status"] == "DEGRADED"

        # Liveness remains intact
        resp_live = await client.get("/api/v1/system/liveness")
        assert resp_live.status_code == 200
        assert resp_live.json()["alive"] is True


@pytest.mark.asyncio
async def test_failure_mode_db_down_readiness(client: AsyncClient):
    """When database is down, readiness probe must reject traffic with 503 Service Unavailable."""
    with patch("app.monitoring.health.check_database_connection", AsyncMock(return_value=False)):
        resp_ready = await client.get("/api/v1/system/readiness")
        assert resp_ready.status_code == 503
        data = resp_ready.json()
        assert data["ready"] is False
        assert data["checks"]["database_connected"] is False


@pytest.mark.asyncio
async def test_failure_mode_ml_unavailable_fallback(db_session):
    """When ML model fails to load, get_final_eta must safely fall back to BASELINE_FALLBACK mode."""
    with patch.object(ml_predictor, "_ensure_loaded", side_effect=ModelUnavailableError("Booster file corrupted")):
        resp = await get_final_eta(
            db_session,
            train_number="12002",
            use_cache=False,
            include_explanations=False,
        )
        assert resp is not None
        assert resp.prediction_mode == PredictionMode.BASELINE_FALLBACK
        for st in resp.stations:
            assert st.final_eta == st.baseline_eta


@pytest.mark.asyncio
async def test_failure_mode_consumer_poison_pill():
    """Malformed messages in Redis stream must be acknowledged and skipped to prevent queue stalling."""
    mock_redis = AsyncMock()
    consumer = StreamingConsumer(redis=mock_redis)

    # Completely corrupted binary payload
    success = await consumer.process_message("9999-1", {"data": "{bad_json:true,"})
    assert success is False
    # Verified: poison pill acknowledged so worker never infinite loops
    mock_redis.xack.assert_called_once()
