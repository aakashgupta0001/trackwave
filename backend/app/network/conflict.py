"""Shared-section and temporal-overlap conflict detection (modules 6, 7, 15).

A shared section alone is not a conflict — module 7 is explicit about this. Two trains
only become a predicted conflict when their (estimated) occupancy windows for that
shared section actually overlap in time, or are scheduled close enough together that a
plausible delay would create an overlap (INSUFFICIENT_SEPARATION).

Directionality (module 35): `TrainRoute.section_id` references one specific, directional
`RailwaySection` row (from_station -> to_station). Two trains whose route entries match
the same section_id are, by construction, traveling the same direction on the same
physical section — there is no separate "reverse" section row in this data model, so a
shared section_id match is always HIGH directional confidence. If a future phase adds
bidirectional/multi-track section modeling, this is the one place that would need to
widen its confidence handling.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.models.route import TrainRoute
from app.network.schemas import ConfidenceLevel, ConflictType, ImpactReason, ImpactSeverity, NetworkConflict, StopWindow


def find_shared_sections(route_a: list[TrainRoute], route_b: list[TrainRoute]) -> list[tuple[TrainRoute, TrainRoute]]:
    """Route entries from A and B that reference the same section_id, i.e. the same
    directional stretch of track — the foundation of all conflict analysis (module 6).
    """
    by_section_b = {r.section_id: r for r in route_b if r.section_id is not None}
    shared = []
    for entry_a in route_a:
        if entry_a.section_id is not None and entry_a.section_id in by_section_b:
            shared.append((entry_a, by_section_b[entry_a.section_id]))
    return shared


def overlap_minutes(window_a: StopWindow, window_b: StopWindow) -> float:
    start = max(window_a.entry_time, window_b.entry_time)
    end = min(window_a.exit_time, window_b.exit_time)
    return max(0.0, (end - start).total_seconds() / 60.0)


def separation_minutes(window_a: StopWindow, window_b: StopWindow) -> float:
    """Gap between the two windows when they don't overlap (0 if they do). Whichever
    train arrives first, this is the time until the other train enters the section.
    """
    if window_a.exit_time <= window_b.entry_time:
        return (window_b.entry_time - window_a.exit_time).total_seconds() / 60.0
    if window_b.exit_time <= window_a.entry_time:
        return (window_a.entry_time - window_b.exit_time).total_seconds() / 60.0
    return 0.0


def _severity_for_overlap(overlap: float, separation: float, settings) -> ImpactSeverity:
    if overlap >= 15:
        return ImpactSeverity.CRITICAL
    if overlap >= 5:
        return ImpactSeverity.HIGH
    if overlap > 0:
        return ImpactSeverity.MEDIUM
    # no overlap — insufficient-separation severity scales with how little buffer remains
    if separation <= settings.NETWORK_MIN_SAFE_SEPARATION_MINUTES / 3:
        return ImpactSeverity.MEDIUM
    return ImpactSeverity.LOW


def detect_section_conflicts(
    train_a_number: str,
    train_b_number: str,
    route_a: list[TrainRoute],
    route_b: list[TrainRoute],
    windows_a: dict[int, StopWindow],
    windows_b: dict[int, StopWindow],
) -> list[NetworkConflict]:
    """All conflicts between two trains across every section they share. Each shared
    section is judged independently — a route can share several sections with mixed
    outcomes (overlap on one, ample separation on another).
    """
    settings = get_settings()
    conflicts: list[NetworkConflict] = []

    for entry_a, entry_b in find_shared_sections(route_a, route_b):
        window_a = windows_a.get(entry_a.section_id)
        window_b = windows_b.get(entry_b.section_id)
        if window_a is None or window_b is None:
            continue

        overlap = overlap_minutes(window_a, window_b)
        station_code = window_a.to_station_code
        if overlap > 0:
            conflicts.append(
                NetworkConflict(
                    conflict_type=ConflictType.SHARED_SECTION_OVERLAP,
                    severity=_severity_for_overlap(overlap, 0.0, settings),
                    train_a=train_a_number,
                    train_b=train_b_number,
                    section_code=window_a.section_code,
                    station_code=station_code,
                    estimated_overlap_minutes=round(overlap, 1),
                    separation_minutes=0.0,
                    directional_confidence=ConfidenceLevel.HIGH,
                    predicted_at=max(window_a.entry_time, window_b.entry_time),
                    reason=ImpactReason(
                        type="SHARED_SECTION",
                        description=(
                            f"Train {train_a_number} is predicted to occupy {window_a.section_code} "
                            f"during part of train {train_b_number}'s scheduled movement window."
                        ),
                        confidence=ConfidenceLevel.MEDIUM,
                    ),
                )
            )
            continue

        separation = separation_minutes(window_a, window_b)
        if separation <= settings.NETWORK_MIN_SAFE_SEPARATION_MINUTES:
            conflicts.append(
                NetworkConflict(
                    conflict_type=ConflictType.INSUFFICIENT_SEPARATION,
                    severity=_severity_for_overlap(0.0, separation, settings),
                    train_a=train_a_number,
                    train_b=train_b_number,
                    section_code=window_a.section_code,
                    station_code=station_code,
                    estimated_overlap_minutes=0.0,
                    separation_minutes=round(separation, 1),
                    directional_confidence=ConfidenceLevel.HIGH,
                    predicted_at=min(window_a.exit_time, window_b.exit_time),
                    reason=ImpactReason(
                        type="SMALL_SEPARATION",
                        description=(
                            f"Small scheduled separation (~{round(separation)} min) between train "
                            f"{train_a_number} and train {train_b_number} on {window_a.section_code} — "
                            "a modest additional delay may be enough to create an overlap."
                        ),
                        confidence=ConfidenceLevel.LOW,
                    ),
                )
            )

    return conflicts
