from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import RailwaySection
from app.schemas.section import RailwaySectionCreate


async def get_by_id(session: AsyncSession, section_id: int) -> RailwaySection | None:
    return await session.get(RailwaySection, section_id)


async def get_by_code(session: AsyncSession, section_code: str) -> RailwaySection | None:
    result = await session.execute(select(RailwaySection).where(RailwaySection.section_code == section_code))
    return result.scalar_one_or_none()


async def get_between(session: AsyncSession, from_station_id: int, to_station_id: int) -> RailwaySection | None:
    """Find the section directly connecting two stations, if one exists."""
    result = await session.execute(
        select(RailwaySection).where(
            RailwaySection.from_station_id == from_station_id,
            RailwaySection.to_station_id == to_station_id,
        )
    )
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[RailwaySection]:
    result = await session.execute(select(RailwaySection).order_by(RailwaySection.section_code))
    return list(result.scalars().all())


async def create(session: AsyncSession, data: RailwaySectionCreate) -> RailwaySection:
    section = RailwaySection(**data.model_dump())
    session.add(section)
    await session.flush()
    return section
