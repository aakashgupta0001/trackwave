"""Phase 11 End-to-End Full System Integration & Failure Mode Validation Tests.

Validates:
1. Complete system pipeline: Provider -> Normalizer -> Stream -> State -> Baseline -> ML -> Uncertainty -> Confidence -> SHAP -> Network Impact -> Alerts -> WebSocket.
2. Standardized API contracts and synonym field availability across Phase 1-10 endpoints.
3. Resilience & Failure Modes:
   - ML model unavailable fallback to deterministic baseline
   - Out-of-order telemetry arrival handling
   - Idempotent duplicate event deduplication
   - Redis unavailability graceful degradation
   - Database failure readiness probe rejection
   - WebSocket envelope serialization contract
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from app.ml.exceptions import ModelUnavailableError
from app.ml.predictor import ml_predictor
from app.models.enums import PredictionMode
from app.network import impact
from app.repositories import alert_repository
from app.services import eta_fusion_service
from app.streaming.pipeline import streaming_pipeline
from app.streaming.schemas import (
    NormalizedTrainEvent,
    StreamEventType,
    WebSocketEnvelope,
    WebSocketMessageType,
)
from app.streaming.state import TrainStateUpdater


@pytest.mark.asyncio
async def test_full_system_pipeline_chain(real_session):
    """End-to-end verification of the unified intelligence pipeline for train 12002."""
    train_number = "12002"
    now = datetime.now(timezone.utc)

    # 1. Telemetry ingestion & normalization
    event = NormalizedTrainEvent(
        event_type=StreamEventType.STATION_DEPARTURE,
        train_number=train_number,
        timestamp=now,
        current_station_code="NDLS",
        next_station_code="MTJ",
        delay_minutes=12.0,
        speed_kmh=80.0,
        current_lat=28.6432,
        current_lng=77.2196,
        source="simulator",
    )

    # 2. Pipeline processing & state update
    predictions = await streaming_pipeline.process_stream_event(real_session, event)
    assert predictions is not None
    assert len(predictions) > 0

    # 3. Fused ETA engine evaluation
    fused_eta = await eta_fusion_service.get_final_eta(
        real_session, train_number, use_cache=False, include_explanations=True
    )
    assert fused_eta is not None
    assert fused_eta.train_number == train_number
    assert len(fused_eta.stations) > 0

    st = fused_eta.stations[0]
    # Check baseline + ML residual relationship
    assert st.baseline_eta is not None
    assert st.final_eta is not None
    assert st.predicted_residual_minutes is not None

    # Check uncertainty interval
    assert st.uncertainty is not None
    assert st.uncertainty.lower_eta <= st.uncertainty.upper_eta
    assert st.uncertainty.interval_width_minutes >= 0

    # Check confidence metrics
    assert st.confidence is not None
    assert 0 <= st.confidence.score <= 100

    # Check explainability factors
    assert st.explanation is not None
    assert len(st.explanation.top_factors) > 0

    # 4. Network cascade impact analysis
    impact_res = await impact.analyze_train_impact(real_session, train_number)
    assert impact_res is not None
    assert 0 <= impact_res.network_impact_score <= 100
    assert hasattr(impact_res, "conflicts")

    # 5. WebSocket envelope contract
    envelope = WebSocketEnvelope(
        topic=f"train:{train_number}",
        event_type=WebSocketMessageType.PREDICTION_UPDATE,
        data={"train_number": train_number, "final_eta": st.final_eta.isoformat()},
        timestamp=now,
    )
    assert envelope.train_number == train_number
    assert envelope.type == "prediction_update"
    serialized = envelope.model_dump_json()
    assert train_number in serialized


@pytest.mark.asyncio
async def test_api_v1_contract_standardization(seeded_client: AsyncClient):
    """Verify Phase 11 standardized API response contracts and backward compatibility."""
    # 1. Check live train endpoint
    resp_live = await seeded_client.get("/api/v1/live/trains/12002")
    assert resp_live.status_code == 200
    live_data = resp_live.json()
    assert live_data["train_number"] == "12002"
    assert "status" in live_data
    assert "provider_status" in live_data
    assert "data_age_seconds" in live_data

    # 2. Check full fused ETA endpoint
    resp_eta = await seeded_client.get("/api/v1/eta/12002")
    assert resp_eta.status_code == 200
    eta_data = resp_eta.json()
    assert eta_data["train_number"] == "12002"
    assert "stations" in eta_data
    assert len(eta_data["stations"]) > 0

    station0 = eta_data["stations"][0]
    # Standardized synonym fields
    assert "scheduled_eta" in station0
    assert "baseline_eta" in station0
    assert "ml_residual_minutes" in station0
    assert "final_eta" in station0
    assert "lower_bound" in station0
    assert "upper_bound" in station0
    assert "confidence_score" in station0
    assert "confidence_level" in station0
    assert "prediction_timestamp" in eta_data


@pytest.mark.asyncio
async def test_system_resilience_ml_failure_baseline_fallback(real_session):
    """When ML model fails to load or infer, ETA engine falls back gracefully to deterministic baseline."""
    with patch.object(ml_predictor, "_ensure_loaded", side_effect=ModelUnavailableError("Simulated model failure")):
        resp = await eta_fusion_service.get_final_eta(
            real_session,
            train_number="12002",
            use_cache=False,
            include_explanations=False,
        )
        assert resp is not None
        assert resp.prediction_mode == PredictionMode.BASELINE_FALLBACK
        for st in resp.stations:
            # Deterministic invariant: final_eta == baseline_eta when ML falls back
            assert st.final_eta == st.baseline_eta
            assert st.predicted_residual_minutes is None or st.predicted_residual_minutes == 0.0


@pytest.mark.asyncio
async def test_system_resilience_out_of_order_telemetry(real_session):
    """Out-of-order telemetry does not roll back or corrupt operational train state."""
    updater = TrainStateUpdater(redis=None)
    train_number = "12002"
    base_time = datetime.now(timezone.utc)

    # Newer event T1
    event_t1 = NormalizedTrainEvent(
        event_type=StreamEventType.STATION_DEPARTURE,
        train_number=train_number,
        timestamp=base_time + timedelta(minutes=10),
        current_station_code="MTJ",
        delay_minutes=5.0,
        speed_kmh=60.0,
        source="simulator",
    )
    is_updated, state1, _ = await updater.process_event(real_session, event_t1)
    assert is_updated is True
    assert state1.current_station_code == "MTJ"

    # Out-of-order older event T0 arriving later
    event_t0 = NormalizedTrainEvent(
        event_type=StreamEventType.STATION_DEPARTURE,
        train_number=train_number,
        timestamp=base_time,  # 10 mins in the past
        current_station_code="NDLS",
        delay_minutes=0.0,
        speed_kmh=10.0,
        source="simulator",
    )
    is_updated_old, state_after_old, _ = await updater.process_event(real_session, event_t0)
    # Must reject advancing the state
    assert is_updated_old is False
    assert state_after_old.current_station_code == "MTJ"  # Kept newer state!


@pytest.mark.asyncio
async def test_system_resilience_idempotent_duplicate_events(real_session):
    """Identical duplicate events are recognized and ignored without corrupting state."""
    updater = TrainStateUpdater(redis=None)
    train_number = "12002"
    now = datetime.now(timezone.utc)

    event = NormalizedTrainEvent(
        event_type=StreamEventType.TRAIN_UPDATE,
        train_number=train_number,
        timestamp=now,
        current_station_code="AGC",
        delay_minutes=15.0,
        speed_kmh=90.0,
        source="simulator",
    )

    # First arrival
    is_updated1, state1, _ = await updater.process_event(real_session, event)
    assert is_updated1 is True

    # Duplicate arrival with same fingerprint
    is_updated2, state2, _ = await updater.process_event(real_session, event)
    assert is_updated2 is False


@pytest.mark.asyncio
async def test_system_resilience_redis_graceful_degradation(real_session):
    """When Redis is unreachable, ETA calculations and pipeline gracefully proceed without error."""
    with patch("app.cache.redis.redis_client.get", side_effect=TimeoutError("Redis connection timeout")):
        with patch("app.cache.redis.redis_client.set", side_effect=TimeoutError("Redis connection timeout")):
            resp = await eta_fusion_service.get_final_eta(
                real_session,
                train_number="12002",
                use_cache=True,
                include_explanations=False,
            )
            assert resp is not None
            assert resp.train_number == "12002"
            assert len(resp.stations) > 0


@pytest.mark.asyncio
async def test_system_resilience_db_disconnect_probes(client: AsyncClient):
    """Health probes accurately reflect database state."""
    with patch("app.monitoring.health.check_database_connection", AsyncMock(return_value=False)):
        resp_ready = await client.get("/api/v1/system/readiness")
        assert resp_ready.status_code == 503
        assert resp_ready.json()["ready"] is False

        # Liveness probe still reports container is alive
        resp_live = await client.get("/api/v1/system/liveness")
        assert resp_live.status_code == 200
        assert resp_live.json()["alive"] is True
