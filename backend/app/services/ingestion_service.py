"""Converts a normalized provider TrainState into a stored TrainEvent — the one place
live-provider data crosses from app/providers/ into the Phase 2 database schema. Reuses
the existing TrainEvent model and event_repository; does not create a parallel table.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventSource
from app.models.train_event import TrainEvent
from app.providers.models import TrainState
from app.repositories import event_repository, section_repository, station_repository, train_repository
from app.schemas.train_event import TrainEventCreate

logger = logging.getLogger(__name__)


async def ingest_train_state(session: AsyncSession, state: TrainState) -> TrainEvent | None:
    """Resolves the train/station/section referenced by `state` and stores it as a
    TrainEvent. Returns None (without raising) if the train doesn't exist in RAILCAST's
    own digital twin — ingestion is best-effort per record, one bad record shouldn't be
    a hard failure for a caller ingesting many trains.

    Idempotent: if a TrainEvent already exists for this (train, provider, timestamp), the
    existing row is returned unchanged rather than inserting a duplicate — the provider
    layer's data_source values are exactly the EventSource values TrainEvent already uses.
    """
    train = await train_repository.get_by_number(session, state.train_number)
    if train is None:
        logger.warning("ingestion skipped: unknown train_number=%s", state.train_number)
        return None

    event_source = EventSource(state.data_source.value)

    existing = await event_repository.find_duplicate(session, train.id, event_source, state.timestamp)
    if existing is not None:
        logger.info(
            "ingestion deduplicated train_number=%s source=%s timestamp=%s event_id=%s",
            state.train_number, event_source.value, state.timestamp.isoformat(), existing.id,
        )
        return existing

    station = await station_repository.get_by_code(session, state.station_code) if state.station_code else None
    section = await section_repository.get_by_code(session, state.section_code) if state.section_code else None

    event = await event_repository.create(
        session,
        TrainEventCreate(
            train_id=train.id,
            timestamp=state.timestamp,
            latitude=state.latitude,
            longitude=state.longitude,
            speed_kmph=state.speed_kmph,
            station_id=station.id if station is not None else None,
            section_id=section.id if section is not None else None,
            delay_minutes=state.delay_minutes or 0,
            event_type=state.event_type,
            event_source=event_source,
            metadata=state.metadata,
        ),
    )
    await session.commit()

    # Phase 6 outcome backfill: when an observed ARRIVAL lands, predictions for that
    # train/station can now record actual_arrival + error_minutes (monitoring data only
    # — never touched during real-time inference). Best-effort, never fatal.
    if state.event_type.value == "ARRIVAL" and station is not None:
        try:
            from app.repositories import prediction_repository

            updated = await prediction_repository.backfill_actual_arrivals(
                session, train.id, station.id, state.timestamp
            )
            if updated:
                await session.commit()
                logger.info("backfilled actual arrival for %d prediction(s) train=%s station=%s",
                            updated, state.train_number, state.station_code)
        except Exception:
            logger.warning("Failed to backfill actual arrivals train=%s", state.train_number, exc_info=True)

    logger.info(
        "ingestion stored train_number=%s source=%s event_type=%s delay_minutes=%s event_id=%s",
        state.train_number, event_source.value, state.event_type.value, event.delay_minutes, event.id,
    )

    # Phase 9: Publish normalized train event to Redis Streams (railcast:train-events)
    try:
        from app.streaming.publisher import event_publisher
        from app.streaming.schemas import normalize_train_state

        norm_event = normalize_train_state(state)
        await event_publisher.publish_event(norm_event)
    except Exception:
        logger.warning("Failed to publish event to Redis stream for train %s", state.train_number, exc_info=True)

    return event
