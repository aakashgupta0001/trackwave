"""Pure unit tests for shared-section/temporal-overlap conflict detection (module 39).
Uses hand-built StopWindow objects — no database needed for the overlap/separation math
itself; find_shared_sections and detect_section_conflicts are exercised with minimal
fake route objects.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.network.conflict import detect_section_conflicts, find_shared_sections, overlap_minutes, separation_minutes
from app.network.schemas import ConflictType, StopWindow

BASE = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _window(section_code: str, start_offset_min: float, duration_min: float, section_id: int = 1) -> StopWindow:
    entry = BASE + timedelta(minutes=start_offset_min)
    return StopWindow(
        section_id=section_id, section_code=section_code, from_station_code="A", to_station_code="B",
        sequence_number=1, entry_time=entry, exit_time=entry + timedelta(minutes=duration_min),
        delay_minutes=0.0, is_estimated=False,
    )


def _fake_route_entry(section_id: int | None) -> SimpleNamespace:
    return SimpleNamespace(section_id=section_id)


# --- overlap / separation math -----------------------------------------------------------

def test_no_temporal_overlap() -> None:
    a = _window("X-Y", 0, 20)
    b = _window("X-Y", 30, 20)
    assert overlap_minutes(a, b) == 0.0
    assert separation_minutes(a, b) == pytest.approx(10.0)


def test_temporal_overlap_detected() -> None:
    a = _window("X-Y", 0, 30)
    b = _window("X-Y", 20, 30)
    assert overlap_minutes(a, b) == pytest.approx(10.0)
    assert separation_minutes(a, b) == 0.0


def test_small_separation_between_windows() -> None:
    a = _window("X-Y", 0, 20)
    b = _window("X-Y", 25, 20)  # 5 min gap
    assert overlap_minutes(a, b) == 0.0
    assert separation_minutes(a, b) == pytest.approx(5.0)


def test_large_separation_between_windows() -> None:
    a = _window("X-Y", 0, 20)
    b = _window("X-Y", 200, 20)
    assert overlap_minutes(a, b) == 0.0
    assert separation_minutes(a, b) == pytest.approx(180.0)


def test_overlap_is_symmetric() -> None:
    a = _window("X-Y", 0, 30)
    b = _window("X-Y", 20, 30)
    assert overlap_minutes(a, b) == overlap_minutes(b, a)


# --- find_shared_sections -----------------------------------------------------------------

def test_find_shared_sections_same_section() -> None:
    route_a = [_fake_route_entry(1), _fake_route_entry(2)]
    route_b = [_fake_route_entry(2), _fake_route_entry(3)]
    shared = find_shared_sections(route_a, route_b)
    assert len(shared) == 1
    assert shared[0][0].section_id == 2


def test_find_shared_sections_different_sections() -> None:
    route_a = [_fake_route_entry(1), _fake_route_entry(2)]
    route_b = [_fake_route_entry(3), _fake_route_entry(4)]
    assert find_shared_sections(route_a, route_b) == []


def test_find_shared_sections_ignores_none_section_id() -> None:
    route_a = [_fake_route_entry(None), _fake_route_entry(2)]
    route_b = [_fake_route_entry(None), _fake_route_entry(2)]
    shared = find_shared_sections(route_a, route_b)
    assert len(shared) == 1  # the None/None pair must not match


# --- detect_section_conflicts (full pipeline, still no DB) --------------------------------

def _route_and_windows(section_id: int, code: str, start: float, duration: float):
    route = [_fake_route_entry(section_id)]
    windows = {section_id: _window(code, start, duration, section_id)}
    return route, windows


def test_same_section_overlap_produces_conflict() -> None:
    route_a, windows_a = _route_and_windows(1, "AGC-GWL", 0, 30)
    route_b, windows_b = _route_and_windows(1, "AGC-GWL", 15, 30)
    conflicts = detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == ConflictType.SHARED_SECTION_OVERLAP
    assert conflicts[0].train_a == "T1" and conflicts[0].train_b == "T2"
    assert "may" in conflicts[0].reason.description or "predicted" in conflicts[0].reason.description


def test_different_sections_produce_no_conflict() -> None:
    route_a, windows_a = _route_and_windows(1, "AGC-GWL", 0, 30)
    route_b, windows_b = _route_and_windows(2, "GWL-JHS", 0, 30)
    assert detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b) == []


def test_same_section_ample_separation_produces_no_conflict() -> None:
    settings = get_settings()
    route_a, windows_a = _route_and_windows(1, "AGC-GWL", 0, 20)
    route_b, windows_b = _route_and_windows(1, "AGC-GWL", 20 + settings.NETWORK_MIN_SAFE_SEPARATION_MINUTES + 30, 20)
    assert detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b) == []


def test_same_section_small_separation_produces_insufficient_separation_conflict() -> None:
    route_a, windows_a = _route_and_windows(1, "AGC-GWL", 0, 20)
    route_b, windows_b = _route_and_windows(1, "AGC-GWL", 25, 20)  # 5 min gap after A exits
    conflicts = detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == ConflictType.INSUFFICIENT_SEPARATION


def test_directional_confidence_is_high_for_matched_section_id() -> None:
    """Same section_id => same directional RailwaySection row => HIGH by construction."""
    route_a, windows_a = _route_and_windows(1, "AGC-GWL", 0, 30)
    route_b, windows_b = _route_and_windows(1, "AGC-GWL", 15, 30)
    conflicts = detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b)
    assert conflicts[0].directional_confidence.value == "HIGH"


def test_multiple_shared_sections_each_judged_independently() -> None:
    route_a = [_fake_route_entry(1), _fake_route_entry(2)]
    route_b = [_fake_route_entry(1), _fake_route_entry(2)]
    windows_a = {1: _window("A-B", 0, 20, 1), 2: _window("B-C", 100, 20, 2)}
    windows_b = {1: _window("A-B", 10, 20, 1), 2: _window("B-C", 500, 20, 2)}  # section 1 overlaps, section 2 doesn't
    conflicts = detect_section_conflicts("T1", "T2", route_a, route_b, windows_a, windows_b)
    types = {c.section_code: c.conflict_type for c in conflicts}
    assert types.get("A-B") == ConflictType.SHARED_SECTION_OVERLAP
    assert "B-C" not in types  # far apart, no conflict at all
