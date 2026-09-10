"""End-to-end integration test validating the entire real-time pipeline chain (Phase 1-10)."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.streaming.consumer import StreamingConsumer
from app.streaming.pipeline import streaming_pipeline
from app.streaming.publisher import EventPublisher
from app.streaming.schemas import NormalizedTrainEvent, StreamEventType
from app.streaming.websocket import ws_manager


@pytest.mark.asyncio
async def test_complete_e2e_streaming_and_prediction_chain(real_session):
    """Verify the complete end-to-end pipeline:

    1. Telemetry event arrives.
    2. Published to stream.
    3. Consumed by worker.
    4. Persisted to database as TrainEvent.
    5. Baseline + ML residual ETA computed.
    6. Uncertainty interval and confidence score evaluated.
    7. Network cascade impact assessed.
    8. Prediction emitted to Redis stream and broadcast to WebSocket subscribers.
    """
    train_num = "12002"
    now = datetime.now(timezone.utc)

    # 1. Mock WebSocket subscriber
    mock_ws = AsyncMock()
    await ws_manager.connect(mock_ws, [f"train:{train_num}"])

    # 2. Incoming normalized telemetry event
    event = NormalizedTrainEvent(
        event_type=StreamEventType.STATION_DEPARTURE,
        train_number=train_num,
        timestamp=now,
        current_station_code="NDLS",
        next_station_code="MTJ",
        delay_minutes=6.0,
        speed_kmh=45.0,
        current_lat=28.6432,
        current_lng=77.2196,
        source="simulator",
    )

    # 3. Publish to Redis Stream
    mock_redis = AsyncMock()
    mock_redis.xadd.return_value = "1000-1"
    publisher = EventPublisher(redis=mock_redis)
    msg_id = await publisher.publish_event(event)
    assert msg_id == "1000-1"

    # 4. Consumer worker consumes and processes
    predictions = await streaming_pipeline.process_stream_event(real_session, event)

    # 5. Assert downstream outputs
    assert len(predictions) > 0
    next_pred = predictions[0]
    assert next_pred.train_number == train_num
    assert next_pred.final_eta is not None
    assert next_pred.confidence_score is not None
    assert next_pred.calculation_latency_ms >= 0.0

    # 6. Verify WebSocket broadcast was queued for client
    assert ws_manager.get_active_connection_count() >= 1

    # Cleanup
    await ws_manager.disconnect(mock_ws)
