from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.route import TrainRoute
from app.models.train import Train
from app.schemas.route import TrainRouteCreate

# Every API-facing use of a route entry needs the station's code+name and (if
# present) the section's code — never just the internal station_id/section_id.
_WITH_STATION_AND_SECTION = (selectinload(TrainRoute.station), selectinload(TrainRoute.section))

# ... plus, when routes are reached via a station (not a train), the train's own
# identity and its source/destination station codes.
_WITH_TRAIN_AND_ITS_STATIONS = (
    selectinload(TrainRoute.train).selectinload(Train.source_station),
    selectinload(TrainRoute.train).selectinload(Train.destination_station),
)


async def list_for_train(session: AsyncSession, train_id: int) -> list[TrainRoute]:
    result = await session.execute(
        select(TrainRoute)
        .where(TrainRoute.train_id == train_id)
        .options(*_WITH_STATION_AND_SECTION)
        .order_by(TrainRoute.sequence_number)
    )
    return list(result.scalars().all())


async def list_for_station(session: AsyncSession, station_id: int) -> list[TrainRoute]:
    """All route entries at a station, across every train — the raw material for the
    station board. Not paginated: bounded by "how many trains stop here," not row growth.
    """
    result = await session.execute(
        select(TrainRoute)
        .where(TrainRoute.station_id == station_id)
        .options(*_WITH_TRAIN_AND_ITS_STATIONS)
        .join(Train, Train.id == TrainRoute.train_id)
        .order_by(Train.train_number)
    )
    return list(result.scalars().all())


async def list_for_station_paginated(
    session: AsyncSession, station_id: int, *, offset: int, limit: int, search: str | None = None
) -> tuple[list[TrainRoute], int]:
    conditions = [TrainRoute.station_id == station_id]
    if search:
        pattern = f"%{search}%"
        conditions.append((Train.train_number.ilike(pattern)) | (Train.train_name.ilike(pattern)))

    base = select(TrainRoute).join(Train, Train.id == TrainRoute.train_id)
    count_stmt = select(func.count()).select_from(TrainRoute).join(Train, Train.id == TrainRoute.train_id)
    for condition in conditions:
        base = base.where(condition)
        count_stmt = count_stmt.where(condition)

    list_stmt = base.options(*_WITH_TRAIN_AND_ITS_STATIONS).order_by(Train.train_number).offset(offset).limit(limit)

    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total


async def create(session: AsyncSession, data: TrainRouteCreate) -> TrainRoute:
    route = TrainRoute(**data.model_dump())
    session.add(route)
    await session.flush()
    return route


async def bulk_create(session: AsyncSession, routes: list[TrainRouteCreate]) -> list[TrainRoute]:
    entries = [TrainRoute(**data.model_dump()) for data in routes]
    session.add_all(entries)
    await session.flush()
    return entries
