"""Tests for the bounded candidate-train graph queries (module 38) against the real
seeded network, plus pure tests for the resolver's schedule-window construction.
"""

from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.network import graph
from app.network.resolver import build_schedule_windows, scheduled_datetime
from app.repositories import section_repository, train_repository

# asyncio_mode = auto (pytest.ini) already handles async test functions; no module-level
# `pytestmark` here since this file also has plain sync tests.


async def test_find_candidate_trains_returns_trains_sharing_a_section(seeded_session: AsyncSession) -> None:
    section = await section_repository.get_by_code(seeded_session, "AGC-GWL")
    assert section is not None
    candidates = await graph.find_candidate_trains(
        seeded_session, section_ids=[section.id], exclude_train_ids=set(), limit=500
    )
    numbers = {t.train_number for t in candidates}
    # 12951, 12002, 12615, 11077 all route through AGC-GWL per the seed network.
    assert {"12951", "12002", "12615", "11077"}.issubset(numbers)


async def test_find_candidate_trains_excludes_given_ids(seeded_session: AsyncSession) -> None:
    section = await section_repository.get_by_code(seeded_session, "AGC-GWL")
    train_12951 = await train_repository.get_by_number(seeded_session, "12951")
    assert section is not None and train_12951 is not None

    candidates = await graph.find_candidate_trains(
        seeded_session, section_ids=[section.id], exclude_train_ids={train_12951.id}, limit=500
    )
    assert train_12951.train_number not in {t.train_number for t in candidates}


async def test_find_candidate_trains_empty_section_list_returns_nothing(seeded_session: AsyncSession) -> None:
    candidates = await graph.find_candidate_trains(seeded_session, section_ids=[], exclude_train_ids=set(), limit=500)
    assert candidates == []


async def test_find_delayed_trains_only_returns_trains_with_delay(seeded_session: AsyncSession) -> None:
    delayed = await graph.find_delayed_trains(seeded_session, min_delay_minutes=1.0, limit=500)
    numbers = {t.train_number for t in delayed}
    # Known from seed data: these four have positive delay_minutes on their latest event.
    assert {"12951", "11077", "12002", "12615"}.issubset(numbers)
    # 14217/12138/12294 have no seeded events at all -> never "delayed".
    assert "14217" not in numbers


def test_scheduled_datetime_combines_date_time_and_day_offset() -> None:
    result = scheduled_datetime(date(2026, 9, 10), time(18, 25), 0)
    assert result == datetime(2026, 9, 10, 18, 25, tzinfo=timezone.utc)

    next_day = scheduled_datetime(date(2026, 9, 10), time(1, 0), 1)
    assert next_day == datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc)


def test_scheduled_datetime_none_for_missing_clock_time() -> None:
    assert scheduled_datetime(date(2026, 9, 10), None, 0) is None


async def test_build_schedule_windows_shifts_by_delay(seeded_session: AsyncSession) -> None:
    from app.services import baseline_eta_service

    _, route, _ = await baseline_eta_service.load_engine_inputs(seeded_session, "12951")
    unshifted = build_schedule_windows(route, date(2026, 9, 10), 0.0)
    shifted = build_schedule_windows(route, date(2026, 9, 10), 10.0)

    section_id = next(iter(unshifted))
    assert (shifted[section_id].entry_time - unshifted[section_id].entry_time).total_seconds() / 60.0 == 10.0
    assert (shifted[section_id].exit_time - unshifted[section_id].exit_time).total_seconds() / 60.0 == 10.0


async def test_terminal_train_has_no_outgoing_window_past_destination(seeded_session: AsyncSession) -> None:
    """Train 14217's route ends at AGC — no section exists past its destination, and
    build_schedule_windows must not fabricate one."""
    from app.services import baseline_eta_service

    _, route, _ = await baseline_eta_service.load_engine_inputs(seeded_session, "14217")
    windows = build_schedule_windows(route, date.today(), 0.0)
    last_stop_section_ids = {r.section_id for r in route if r.section_id is not None}
    assert set(windows.keys()) == last_stop_section_ids
