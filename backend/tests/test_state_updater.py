"""Tests for TrainStateUpdater out-of-order event handling and deterministic deduplication."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.streaming.schemas import NormalizedTrainEvent, StreamEventType
from app.streaming.state import TrainStateUpdater


@pytest.mark.asyncio
async def test_state_updater_deduplication():
    mock_redis = AsyncMock()
    updater = TrainStateUpdater(redis=mock_redis)

    now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
    ev = NormalizedTrainEvent(
        train_number="12002",
        timestamp=now,
        current_station_code="NDLS",
        delay_minutes=0.0,
    )

    fp = ev.fingerprint
    assert not updater.is_duplicate(fp)
    updater.mark_seen(fp)
    assert updater.is_duplicate(fp)


@pytest.mark.asyncio
async def test_state_updater_out_of_order_handling(real_session):
    mock_redis = AsyncMock()
    updater = TrainStateUpdater(redis=mock_redis)

    t1 = datetime.now(timezone.utc) - timedelta(minutes=5)
    t2 = datetime.now(timezone.utc)
    t_old = datetime.now(timezone.utc) - timedelta(minutes=10)

    # 1. First event at t1 (delay 5)
    ev1 = NormalizedTrainEvent(
        train_number="12002",
        timestamp=t1,
        current_station_code="NDLS",
        delay_minutes=5.0,
        speed_kmh=60.0,
        source="test",
    )
    is_new, state1, db_ev1 = await updater.process_event(real_session, ev1)
    assert is_new is True
    assert state1 is not None
    assert state1.delay_minutes == 5.0
    assert db_ev1 is not None

    # 2. Forward event at t2 (delay 10)
    ev2 = NormalizedTrainEvent(
        train_number="12002",
        timestamp=t2,
        current_station_code="MTJ",
        delay_minutes=10.0,
        speed_kmh=90.0,
        source="test",
    )
    is_new, state2, db_ev2 = await updater.process_event(real_session, ev2)
    assert is_new is True
    assert state2.delay_minutes == 10.0
    assert state2.current_station_code == "MTJ"
    assert state2.prev_delay_minutes == 5.0

    # 3. Out-of-order event at t_old (delay 20) — arrives late
    ev_old = NormalizedTrainEvent(
        train_number="12002",
        timestamp=t_old,
        current_station_code="NDLS",
        delay_minutes=20.0,
        speed_kmh=30.0,
        source="test",
    )
    is_new, state_after_old, db_ev_old = await updater.process_event(real_session, ev_old)
    # Operational state MUST NOT regress to t_old!
    assert is_new is False
    assert state_after_old.last_event_time == t2
    assert state_after_old.delay_minutes == 10.0
    # But DB record must still have been persisted
    assert db_ev_old is not None
    assert db_ev_old.delay_minutes == 20
