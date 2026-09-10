"""Tests for continuous PredictionStreamingPipeline debouncing and execution."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.eta import BaselineEtaResponse, EtaStation
from app.streaming.pipeline import PredictionStreamingPipeline
from app.streaming.schemas import NormalizedTrainEvent, StreamEventType


def test_debouncing_logic():
    pipeline = PredictionStreamingPipeline()
    train_num = "12002"

    # First event: should NOT debounce
    assert pipeline.should_debounce_prediction(train_num) is False

    # Simulate prediction ran now
    import time
    pipeline._last_prediction_time[train_num] = time.monotonic()

    # Immediate second check: SHOULD debounce (< 5.0s)
    assert pipeline.should_debounce_prediction(train_num) is True

    # Simulate 6 seconds passed
    pipeline._last_prediction_time[train_num] = time.monotonic() - 6.0
    assert pipeline.should_debounce_prediction(train_num) is False


@pytest.mark.asyncio
async def test_pipeline_process_stream_event(real_session):
    pipeline = PredictionStreamingPipeline()
    train_num = "12002"

    now = datetime.now(timezone.utc)
    ev = NormalizedTrainEvent(
        train_number=train_num,
        timestamp=now,
        current_station_code="NDLS",
        next_station_code="MTJ",
        delay_minutes=4.0,
        speed_kmh=80.0,
        source="test",
    )

    preds = await pipeline.process_stream_event(real_session, ev)
    assert isinstance(preds, list)
    if preds:
        pred = preds[0]
        assert pred.train_number == train_num
        assert pred.calculation_latency_ms >= 0.0

    # Immediate second event: must be debounced
    ev2 = NormalizedTrainEvent(
        train_number=train_num,
        timestamp=now + timedelta(seconds=1),
        current_station_code="NDLS",
        delay_minutes=4.0,
        speed_kmh=82.0,
        source="test",
    )
    preds2 = await pipeline.process_stream_event(real_session, ev2)
    assert preds2 == []  # Debounced, so no new prediction recalculation emitted
