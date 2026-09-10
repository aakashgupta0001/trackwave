"""Tests for Phase 9 real-time streaming schemas, event publisher, and consumer."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.streaming.consumer import StreamingConsumer
from app.streaming.publisher import EventPublisher
from app.streaming.schemas import (
    NormalizedTrainEvent,
    PredictionUpdatePayload,
    StreamEventType,
    WebSocketEnvelope,
    WebSocketMessageType,
)


def test_normalized_train_event_fingerprint():
    now = datetime(2026, 3, 10, 10, 0, 0, tzinfo=timezone.utc)
    ev1 = NormalizedTrainEvent(
        train_number="12002",
        timestamp=now,
        current_station_code="NDLS",
        delay_minutes=5.0,
        speed_kmh=100.0,
    )
    ev2 = NormalizedTrainEvent(
        train_number="12002",
        timestamp=now,
        current_station_code="NDLS",
        delay_minutes=5.0,
        speed_kmh=100.0,
    )
    assert ev1.fingerprint is not None
    assert ev1.fingerprint == ev2.fingerprint

    # Change one field -> fingerprint changes
    ev3 = NormalizedTrainEvent(
        train_number="12002",
        timestamp=now,
        current_station_code="NDLS",
        delay_minutes=15.0,
        speed_kmh=100.0,
    )
    assert ev1.fingerprint != ev3.fingerprint


def test_prediction_update_payload_serialization():
    now = datetime(2026, 3, 10, 10, 0, 0, tzinfo=timezone.utc)
    payload = PredictionUpdatePayload(
        train_number="12002",
        station_code="GWL",
        scheduled_arrival=now,
        baseline_arrival=now,
        final_eta=now,
        delay_minutes=10.0,
        confidence_score=85,
        network_impact_score=40,
        calculation_latency_ms=12.5,
    )
    dumped = payload.model_dump_json()
    assert "12002" in dumped
    assert "GWL" in dumped

    reconstructed = PredictionUpdatePayload.model_validate_json(dumped)
    assert reconstructed.train_number == "12002"
    assert reconstructed.confidence_score == 85


def test_websocket_envelope():
    env = WebSocketEnvelope(
        topic="train:12002",
        event_type=WebSocketMessageType.PREDICTION_UPDATE,
        data={"train_number": "12002", "delay": 5},
    )
    json_str = env.model_dump_json()
    assert "train:12002" in json_str
    assert "prediction_update" in json_str


@pytest.mark.asyncio
async def test_event_publisher():
    mock_redis = AsyncMock()
    mock_redis.xadd.return_value = "1710000000000-0"

    publisher = EventPublisher(redis=mock_redis)
    event = NormalizedTrainEvent(
        train_number="12002",
        timestamp=datetime.now(timezone.utc),
        delay_minutes=0.0,
    )

    msg_id = await publisher.publish_event(event)
    assert msg_id == "1710000000000-0"
    mock_redis.xadd.assert_called_once()

    # Prediction publishing
    pred = PredictionUpdatePayload(train_number="12002", station_code="AGC")
    pred_msg_id = await publisher.publish_prediction(pred)
    assert pred_msg_id == "1710000000000-0"


@pytest.mark.asyncio
async def test_streaming_consumer_process_poison_pill():
    mock_redis = AsyncMock()
    consumer = StreamingConsumer(redis=mock_redis)

    # Poison pill invalid json
    res = await consumer.process_message("100-1", {"data": "not-a-json"})
    assert res is False
    # Should ACK poison pill so it does not block the queue
    mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
async def test_system_streaming_status_endpoint(client):
    response = await client.get("/api/v1/system/streaming/status")
    assert response.status_code == 200
    data = response.json()
    assert "streaming_enabled" in data
    assert "worker_status" in data
    assert "redis_streams" in data
    assert "metrics" in data
    assert "websockets" in data
