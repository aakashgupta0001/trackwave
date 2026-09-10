"""Tests for network delay cascade recalculation trigger conditions."""

from datetime import datetime, timezone
import time

from app.streaming.pipeline import PredictionStreamingPipeline
from app.streaming.schemas import NormalizedTrainEvent, StreamEventType
from app.streaming.state import ActiveTrainState


def test_network_trigger_evaluation():
    pipeline = PredictionStreamingPipeline()
    train_num = "12002"
    now = datetime.now(timezone.utc)

    # 1. First time seeing train -> True
    ev = NormalizedTrainEvent(
        train_number=train_num,
        timestamp=now,
        delay_minutes=5.0,
        event_type=StreamEventType.GPS_UPDATE,
    )
    state = ActiveTrainState(
        train_number=train_num,
        last_event_id="e1",
        last_event_time=now,
        last_event_type="gps_update",
        delay_minutes=5.0,
    )
    assert pipeline.should_trigger_network_recalc(ev, state) is True

    # Mark that network analysis ran now
    pipeline._last_network_recalc_time[train_num] = time.monotonic()

    # 2. Within rate limit window (< 30s) -> False even if delay changed
    state_jump = ActiveTrainState(
        train_number=train_num,
        last_event_id="e2",
        last_event_time=now,
        last_event_type="gps_update",
        delay_minutes=25.0,
        prev_delay_minutes=5.0,
    )
    assert pipeline.should_trigger_network_recalc(ev, state_jump) is False

    # 3. After rate limit window (> 30s):
    pipeline._last_network_recalc_time[train_num] = time.monotonic() - 35.0

    # Case A: Small delay change (< 2.0 min) & small distance -> False
    ev_minor = NormalizedTrainEvent(
        train_number=train_num,
        timestamp=now,
        delay_minutes=5.5,
        event_type=StreamEventType.GPS_UPDATE,
    )
    state_minor = ActiveTrainState(
        train_number=train_num,
        last_event_id="e3",
        last_event_time=now,
        last_event_type="gps_update",
        delay_minutes=5.5,
        prev_delay_minutes=5.0,
        current_lat=28.100,
        current_lng=77.200,
        prev_lat=28.101,
        prev_lng=77.201,
    )
    assert pipeline.should_trigger_network_recalc(ev_minor, state_minor) is False

    # Case B: Significant delay change (>= 2.0 min) -> True
    state_significant = ActiveTrainState(
        train_number=train_num,
        last_event_id="e4",
        last_event_time=now,
        last_event_type="gps_update",
        delay_minutes=12.0,
        prev_delay_minutes=5.0,  # delta = 7.0 min >= 2.0 min
    )
    assert pipeline.should_trigger_network_recalc(ev, state_significant) is True

    # Case C: Station arrival -> True
    ev_arrival = NormalizedTrainEvent(
        train_number=train_num,
        timestamp=now,
        delay_minutes=5.0,
        event_type=StreamEventType.STATION_ARRIVAL,
    )
    assert pipeline.should_trigger_network_recalc(ev_arrival, state_minor) is True
