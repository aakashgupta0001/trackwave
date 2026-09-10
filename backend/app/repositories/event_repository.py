from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import EventSource, EventType
from app.models.train_event import TrainEvent
from app.schemas.train_event import TrainEventCreate

# Every API-facing use of an event needs the station/section code, never just the ID.
_WITH_STATION_AND_SECTION = (selectinload(TrainEvent.station), selectinload(TrainEvent.section))


async def create(session: AsyncSession, data: TrainEventCreate) -> TrainEvent:
    payload = data.model_dump(exclude={"metadata"})
    event = TrainEvent(event_metadata=data.metadata, **payload)
    session.add(event)
    await session.flush()
    return event


async def find_duplicate(
    session: AsyncSession, train_id: int, event_source: EventSource, timestamp: datetime
) -> TrainEvent | None:
    """Used by the ingestion service (Phase 4) for idempotency: a provider re-reporting
    the same (train, source, timestamp) shouldn't create a second identical event.
    """
    result = await session.execute(
        select(TrainEvent)
        .where(
            TrainEvent.train_id == train_id,
            TrainEvent.event_source == event_source,
            TrainEvent.timestamp == timestamp,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_for_train(session: AsyncSession, train_id: int) -> TrainEvent | None:
    """The single source of truth for "what do we currently know about this train."
    Ordered by timestamp, with event id as a stable tiebreaker for equal timestamps.
    """
    result = await session.execute(
        select(TrainEvent)
        .where(TrainEvent.train_id == train_id)
        .options(*_WITH_STATION_AND_SECTION)
        .order_by(TrainEvent.timestamp.desc(), TrainEvent.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_recent_for_train(session: AsyncSession, train_id: int, *, limit: int = 2) -> list[TrainEvent]:
    """The N most recent events, newest first — bounded history for ML delay-trend
    features (callers must further restrict to timestamp <= prediction time)."""
    result = await session.execute(
        select(TrainEvent)
        .where(TrainEvent.train_id == train_id)
        .options(*_WITH_STATION_AND_SECTION)
        .order_by(TrainEvent.timestamp.desc(), TrainEvent.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_latest_for_trains(session: AsyncSession, train_ids: list[int]) -> dict[int, TrainEvent]:
    """Batched version of get_latest_for_train — one query for many trains (e.g. every
    train on a station board), using PostgreSQL's DISTINCT ON instead of one query per
    train, which would otherwise be an N+1 query pattern.
    """
    if not train_ids:
        return {}
    result = await session.execute(
        select(TrainEvent)
        .where(TrainEvent.train_id.in_(train_ids))
        .options(*_WITH_STATION_AND_SECTION)
        .order_by(TrainEvent.train_id, TrainEvent.timestamp.desc(), TrainEvent.id.desc())
        .distinct(TrainEvent.train_id)
    )
    events = result.scalars().all()
    return {event.train_id: event for event in events}


async def list_paginated_for_train(
    session: AsyncSession,
    train_id: int,
    *,
    offset: int,
    limit: int,
    event_type: EventType | None = None,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
) -> tuple[list[TrainEvent], int]:
    conditions = [TrainEvent.train_id == train_id]
    if event_type is not None:
        conditions.append(TrainEvent.event_type == event_type)
    if from_timestamp is not None:
        conditions.append(TrainEvent.timestamp >= from_timestamp)
    if to_timestamp is not None:
        conditions.append(TrainEvent.timestamp <= to_timestamp)

    count_stmt = select(func.count()).select_from(TrainEvent)
    list_stmt = select(TrainEvent).options(*_WITH_STATION_AND_SECTION)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    list_stmt = list_stmt.order_by(TrainEvent.timestamp.desc(), TrainEvent.id.desc()).offset(offset).limit(limit)

    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total
