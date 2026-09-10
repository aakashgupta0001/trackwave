from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import StationType
from app.models.station import Station
from app.schemas.station import StationCreate


async def get_by_id(session: AsyncSession, station_id: int) -> Station | None:
    return await session.get(Station, station_id)


async def get_by_code(session: AsyncSession, station_code: str) -> Station | None:
    result = await session.execute(select(Station).where(Station.station_code == station_code))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Station]:
    result = await session.execute(select(Station).order_by(Station.station_code))
    return list(result.scalars().all())


async def create(session: AsyncSession, data: StationCreate) -> Station:
    station = Station(**data.model_dump())
    session.add(station)
    await session.flush()
    return station


async def list_paginated(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    search: str | None = None,
    zone: str | None = None,
    state: str | None = None,
    station_type: StationType | None = None,
) -> tuple[list[Station], int]:
    """Filtered, paginated station listing. Returns (items, total_matching_count)."""
    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(or_(Station.station_code.ilike(pattern), Station.station_name.ilike(pattern)))
    if zone is not None:
        conditions.append(Station.zone == zone)
    if state is not None:
        conditions.append(Station.state == state)
    if station_type is not None:
        conditions.append(Station.station_type == station_type)

    count_stmt = select(func.count()).select_from(Station)
    list_stmt = select(Station).order_by(Station.station_code)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    list_stmt = list_stmt.offset(offset).limit(limit)

    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total
