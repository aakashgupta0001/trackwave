"""Ingestion service tests: converting a normalized TrainState into a stored TrainEvent,
including idempotency (duplicate protection) against the real database.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.train_event import TrainEvent
from app.providers.models import ProviderName, TrainState
from app.services import ingestion_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def cleanup_ingested_events(real_session: AsyncSession) -> None:
    """ingestion_service commits, so events written here would otherwise persist and
    pollute later test runs (e.g. the Phase 3 pagination tests that count seed events).
    Delete anything these tests ingested once they're done."""
    yield
    await real_session.execute(
        delete(TrainEvent).where(TrainEvent.event_metadata["note"].astext == "ingestion test")
    )
    await real_session.commit()


def _state(**overrides) -> TrainState:
    defaults = dict(
        train_number="12951",
        journey_date=datetime.now(timezone.utc).date(),
        timestamp=datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        latitude=27.3,
        longitude=77.85,
        speed_kmph=88.0,
        station_code=None,
        section_code="MTJ-AGC",
        delay_minutes=6,
        data_source=ProviderName.SIMULATOR,
        retrieved_at=datetime.now(timezone.utc),
        metadata={"note": "ingestion test"},
    )
    defaults.update(overrides)
    return TrainState(**defaults)


async def test_ingest_creates_a_train_event(seeded_session: AsyncSession, cleanup_ingested_events: None) -> None:
    state = _state(timestamp=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc))
    event = await ingestion_service.ingest_train_state(seeded_session, state)

    assert event is not None
    assert event.event_source.value == "SIMULATOR"
    assert event.section_id is not None
    assert event.delay_minutes == 6
    assert event.event_metadata == {"note": "ingestion test"}


async def test_ingest_is_idempotent_for_same_provider_timestamp(seeded_session: AsyncSession, cleanup_ingested_events: None) -> None:
    state = _state(timestamp=datetime(2026, 1, 2, 9, 0, 0, tzinfo=timezone.utc))

    first = await ingestion_service.ingest_train_state(seeded_session, state)
    second = await ingestion_service.ingest_train_state(seeded_session, state)

    assert first is not None
    assert second is not None
    assert first.id == second.id  # no duplicate row created

    count = (
        await seeded_session.execute(
            select(func.count()).select_from(TrainEvent).where(
                TrainEvent.train_id == first.train_id,
                TrainEvent.event_source == first.event_source,
                TrainEvent.timestamp == first.timestamp,
            )
        )
    ).scalar_one()
    assert count == 1


async def test_ingest_unknown_train_is_skipped_not_raised(seeded_session: AsyncSession) -> None:
    state = _state(train_number="99999", timestamp=datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc))
    result = await ingestion_service.ingest_train_state(seeded_session, state)
    assert result is None
