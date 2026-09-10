from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventType, TrainType
from app.models.route import TrainRoute
from app.models.train import Train
from app.models.train_event import TrainEvent
from app.repositories import event_repository, route_repository, train_repository
from app.services.exceptions import NotFoundError


async def _get_train_or_raise(session: AsyncSession, train_number: str) -> Train:
    train = await train_repository.get_by_number(session, train_number)
    if train is None:
        raise NotFoundError(f"Train {train_number} not found")
    return train


async def list_trains_paginated(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    search: str | None = None,
    train_type: TrainType | None = None,
    zone: str | None = None,
    active: bool | None = None,
) -> tuple[list[Train], int]:
    return await train_repository.list_paginated(
        session, offset=offset, limit=limit, search=search, train_type=train_type, zone=zone, active=active
    )


async def get_train_with_route(session: AsyncSession, train_number: str) -> Train:
    train = await train_repository.get_by_number(session, train_number, with_routes=True)
    if train is None:
        raise NotFoundError(f"Train {train_number} not found")
    return train


async def list_active_trains(session: AsyncSession) -> list[Train]:
    return await train_repository.list_all(session, active_only=True)


async def get_train_route(session: AsyncSession, train_number: str) -> tuple[Train, list[TrainRoute]]:
    train = await _get_train_or_raise(session, train_number)
    route = await route_repository.list_for_train(session, train.id)
    return train, route


async def get_train_state(session: AsyncSession, train_number: str) -> tuple[Train, TrainEvent | None]:
    train = await _get_train_or_raise(session, train_number)
    latest_event = await event_repository.get_latest_for_train(session, train.id)
    return train, latest_event


async def list_train_events_paginated(
    session: AsyncSession,
    train_number: str,
    *,
    offset: int,
    limit: int,
    event_type: EventType | None = None,
    from_timestamp: datetime | None = None,
    to_timestamp: datetime | None = None,
) -> tuple[Train, list[TrainEvent], int]:
    train = await _get_train_or_raise(session, train_number)
    events, total = await event_repository.list_paginated_for_train(
        session,
        train.id,
        offset=offset,
        limit=limit,
        event_type=event_type,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )
    return train, events, total


def _compute_upcoming_route(route: list[TrainRoute], latest_event: TrainEvent | None) -> list[TrainRoute]:
    """Which route entries the train hasn't reached yet, based purely on the latest
    known TrainEvent — no ETA/prediction involved, just "where are we on the static
    timetable." Falls back to the full route whenever position can't be determined.
    """
    if latest_event is None:
        return route

    if latest_event.station_id is not None:
        # Train's latest known event is *at* a station: that station has been reached,
        # so only strictly later stops are upcoming.
        current = next((r for r in route if r.station_id == latest_event.station_id), None)
        if current is not None:
            return [r for r in route if r.sequence_number > current.sequence_number]
        return route

    if latest_event.section_id is not None and latest_event.section is not None:
        # Train is between stations, heading toward the section's destination station,
        # which — along with everything after it — hasn't been reached yet.
        next_station_id = latest_event.section.to_station_id
        upcoming_start = next((r for r in route if r.station_id == next_station_id), None)
        if upcoming_start is not None:
            return [r for r in route if r.sequence_number >= upcoming_start.sequence_number]
        return route

    return route


async def get_upcoming_route(
    session: AsyncSession, train_number: str
) -> tuple[Train, TrainEvent | None, list[TrainRoute]]:
    train = await _get_train_or_raise(session, train_number)
    route = await route_repository.list_for_train(session, train.id)
    latest_event = await event_repository.get_latest_for_train(session, train.id)
    upcoming = _compute_upcoming_route(route, latest_event)
    return train, latest_event, upcoming
