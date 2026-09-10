"""Verifies the seed script (scripts/seed.py) is idempotent and produces a railway
network whose route graph is actually valid — every consecutive station pair in every
train's route must correspond to a real RailwaySection. Future ETA calculations depend
on this holding true, so it's tested explicitly (Phase 2 spec, module 22).

These tests commit against the real database (not the rollback-per-test fixture) since
they're exercising the seed script's real, idempotent behavior.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import TrainRoute
from app.models.section import RailwaySection
from app.models.station import Station
from app.models.train import Train
from app.models.train_event import TrainEvent
from app.repositories import section_repository
from scripts.seed import EVENTS, SECTIONS, STATIONS, TRAINS, run_seed

pytestmark = pytest.mark.asyncio


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def test_seed_is_idempotent(real_session: AsyncSession) -> None:
    await run_seed()
    first_stations = await _count(real_session, Station)
    first_sections = await _count(real_session, RailwaySection)
    first_trains = await _count(real_session, Train)
    first_routes = await _count(real_session, TrainRoute)
    first_events = await _count(real_session, TrainEvent)

    await run_seed()
    second_stations = await _count(real_session, Station)
    second_sections = await _count(real_session, RailwaySection)
    second_trains = await _count(real_session, Train)
    second_routes = await _count(real_session, TrainRoute)
    second_events = await _count(real_session, TrainEvent)

    assert first_stations == second_stations
    assert first_sections == second_sections
    assert first_trains == second_trains
    assert first_routes == second_routes
    assert first_events == second_events


async def test_seed_creates_expected_sample_data(real_session: AsyncSession) -> None:
    await run_seed()

    seeded_codes = {s["station_code"] for s in STATIONS}
    result = await real_session.execute(select(Station.station_code).where(Station.station_code.in_(seeded_codes)))
    assert {row[0] for row in result.all()} == seeded_codes

    seeded_section_codes = {s["section_code"] for s in SECTIONS}
    result = await real_session.execute(
        select(RailwaySection.section_code).where(RailwaySection.section_code.in_(seeded_section_codes))
    )
    assert {row[0] for row in result.all()} == seeded_section_codes

    seeded_train_numbers = {t["train_number"] for t in TRAINS}
    result = await real_session.execute(select(Train.train_number).where(Train.train_number.in_(seeded_train_numbers)))
    assert {row[0] for row in result.all()} == seeded_train_numbers

    expected_route_entries = sum(len(t["route"]) for t in TRAINS)
    result = await real_session.execute(
        select(func.count())
        .select_from(TrainRoute)
        .join(Train, Train.id == TrainRoute.train_id)
        .where(Train.train_number.in_(seeded_train_numbers))
    )
    assert result.scalar_one() == expected_route_entries

    assert await _count(real_session, TrainEvent) >= len(EVENTS)


async def test_seeded_train_routes_form_a_valid_railway_graph(real_session: AsyncSession) -> None:
    """For every seeded train and every consecutive stop pair, a RailwaySection must
    connect them — independently re-derived here, not just trusted from stored section_id.
    """
    await run_seed()

    result = await real_session.execute(select(Train))
    trains = list(result.scalars().all())
    assert len(trains) >= len(TRAINS)

    checked_pairs = 0
    for train in trains:
        route_result = await real_session.execute(
            select(TrainRoute).where(TrainRoute.train_id == train.id).order_by(TrainRoute.sequence_number)
        )
        route = list(route_result.scalars().all())
        assert route, f"Train {train.train_number} has no route entries"
        assert [r.sequence_number for r in route] == list(range(1, len(route) + 1))

        for previous_stop, current_stop in zip(route, route[1:]):
            section = await section_repository.get_between(
                real_session, previous_stop.station_id, current_stop.station_id
            )
            assert section is not None, (
                f"Train {train.train_number}: no RailwaySection connects station "
                f"{previous_stop.station_id} -> {current_stop.station_id}"
            )
            assert current_stop.section_id == section.id
            checked_pairs += 1

    assert checked_pairs == sum(len(t["route"]) - 1 for t in TRAINS)
