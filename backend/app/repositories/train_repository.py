from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import TrainType
from app.models.train import Train
from app.schemas.train import TrainCreate

# Eager-loaded on every list/detail query: every API-facing schema needs the
# source/destination station's code+name, never just the internal station_id.
_WITH_STATIONS = (selectinload(Train.source_station), selectinload(Train.destination_station))


async def get_by_id(session: AsyncSession, train_id: int, with_routes: bool = False) -> Train | None:
    if with_routes:
        result = await session.execute(
            select(Train).where(Train.id == train_id).options(selectinload(Train.routes), *_WITH_STATIONS)
        )
        return result.scalar_one_or_none()
    return await session.get(Train, train_id)


async def get_by_number(session: AsyncSession, train_number: str, with_routes: bool = False) -> Train | None:
    stmt = select(Train).where(Train.train_number == train_number).options(*_WITH_STATIONS)
    if with_routes:
        stmt = stmt.options(selectinload(Train.routes))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_paginated(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    search: str | None = None,
    train_type: TrainType | None = None,
    zone: str | None = None,
    active: bool | None = None,
) -> tuple[list[Train], int]:
    """Filtered, paginated train listing. Returns (items, total_matching_count)."""
    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(or_(Train.train_number.ilike(pattern), Train.train_name.ilike(pattern)))
    if train_type is not None:
        conditions.append(Train.train_type == train_type)
    if zone is not None:
        conditions.append(Train.zone == zone)
    if active is not None:
        conditions.append(Train.active.is_(active))

    count_stmt = select(func.count()).select_from(Train)
    list_stmt = select(Train).options(*_WITH_STATIONS).order_by(Train.train_number)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    list_stmt = list_stmt.offset(offset).limit(limit)

    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total


async def list_all(session: AsyncSession, active_only: bool = False) -> list[Train]:
    stmt = select(Train).order_by(Train.train_number)
    if active_only:
        stmt = stmt.where(Train.active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create(session: AsyncSession, data: TrainCreate) -> Train:
    train = Train(**data.model_dump())
    session.add(train)
    await session.flush()
    return train
