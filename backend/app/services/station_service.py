from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StationType
from app.models.station import Station
from app.repositories import event_repository, route_repository, station_repository
from app.schemas.station import StationBoardItem, StationBoardResponse, StationTrainItem
from app.services.exceptions import NotFoundError


async def get_station(session: AsyncSession, station_code: str) -> Station:
    station = await station_repository.get_by_code(session, station_code)
    if station is None:
        raise NotFoundError(f"Station {station_code} not found")
    return station


async def list_stations(session: AsyncSession) -> list[Station]:
    return await station_repository.list_all(session)


async def list_stations_paginated(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    search: str | None = None,
    zone: str | None = None,
    state: str | None = None,
    station_type: StationType | None = None,
) -> tuple[list[Station], int]:
    return await station_repository.list_paginated(
        session, offset=offset, limit=limit, search=search, zone=zone, state=state, station_type=station_type
    )


async def get_station_board(session: AsyncSession, station_code: str) -> StationBoardResponse:
    station = await get_station(session, station_code)
    routes = await route_repository.list_for_station(session, station.id)

    train_ids = list({route.train_id for route in routes})
    latest_events = await event_repository.get_latest_for_trains(session, train_ids)

    board = [StationBoardItem.build(route, latest_events.get(route.train_id)) for route in routes]

    return StationBoardResponse(
        station_code=station.station_code,
        station_name=station.station_name,
        generated_at=datetime.now(timezone.utc),
        board=board,
    )


async def list_station_trains_paginated(
    session: AsyncSession, station_code: str, *, offset: int, limit: int, search: str | None = None
) -> tuple[Station, list[StationTrainItem], int]:
    station = await get_station(session, station_code)
    routes, total = await route_repository.list_for_station_paginated(
        session, station.id, offset=offset, limit=limit, search=search
    )
    items = [StationTrainItem.from_route(route) for route in routes]
    return station, items, total
