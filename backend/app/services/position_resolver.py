"""Reusable train-position resolution for the baseline ETA engine (Phase 5).

Turns the latest known TrainEvent plus the train's static route into a normalized
"where is this train on its journey" answer, without fabricating a location: when the
evidence doesn't determine a position, the resolver says so explicitly (PositionSource
NO_EVENT / UNKNOWN) instead of guessing.

Position states handled (Phase 5 spec, module 3):
  A. latest event at a known route station          → AT_STATION / DEPARTED_STATION
  B. latest event inside a known railway section    → IN_SECTION
  C. latest event with GPS only (no station/section)→ GPS_ONLY (approximate resolution)
  D. no latest event at all                         → NO_EVENT
  E. latest event references a station/section that  → UNKNOWN (route mismatch /
     isn't on this train's route                              already passed)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.models.route import TrainRoute
from app.models.train_event import TrainEvent
from app.utils.geo import fraction_along_section, haversine_distance_km

logger = logging.getLogger(__name__)


class PositionSource(str, Enum):
    """How the engine knows where the train is — exposed for explainability."""

    LATEST_TRAIN_EVENT_STATION = "LATEST_TRAIN_EVENT_STATION"
    LATEST_TRAIN_EVENT_SECTION = "LATEST_TRAIN_EVENT_SECTION"
    LATEST_TRAIN_EVENT_GPS = "LATEST_TRAIN_EVENT_GPS"
    NO_EVENT = "NO_EVENT"
    UNKNOWN = "UNKNOWN"


class PositionKind(str, Enum):
    AT_STATION = "AT_STATION"
    DEPARTED_STATION = "DEPARTED_STATION"
    IN_SECTION = "IN_SECTION"
    GPS_ONLY = "GPS_ONLY"
    NO_POSITION = "NO_POSITION"


@dataclass
class PositionResolution:
    """Where the train currently is, in route terms.

    first_upcoming_index is the index into the (deduplicated, ordered) route list of the
    first station the train has NOT yet reached — None when the journey can't be placed
    or the train is at/beyond its destination.
    """

    kind: PositionKind
    position_source: PositionSource
    first_upcoming_index: int | None
    # The section the train is currently travelling through, when known.
    current_section_entry_index: int | None = None  # route index of the section's destination station
    fraction_remaining_in_section: float | None = None  # 0..1, None when progress is unknown
    last_known_station_code: str | None = None
    next_station_code: str | None = None
    notes: list[str] = field(default_factory=list)


def dedupe_route(route: list[TrainRoute]) -> list[TrainRoute]:
    """Route entries ordered by sequence_number with duplicate stations dropped — a
    malformed route must not crash or silently double-count the ETA walk. The first
    occurrence (lowest sequence number) wins.
    """
    seen: set[int] = set()
    ordered = sorted(route, key=lambda r: r.sequence_number)
    unique: list[TrainRoute] = []
    for entry in ordered:
        if entry.station_id in seen:
            logger.warning("Duplicate station_id=%s in train route — dropping later entry seq=%s",
                           entry.station_id, entry.sequence_number)
            continue
        seen.add(entry.station_id)
        unique.append(entry)
    return unique


def _route_index_by_station(route: list[TrainRoute]) -> dict[int, int]:
    return {entry.station_id: i for i, entry in enumerate(route)}


def resolve_position(
    latest_event: TrainEvent | None,
    route: list[TrainRoute],
    *,
    gps_station_proximity_km: float = 2.0,
) -> PositionResolution:
    """Resolve the train's current position from its latest event and static route.

    Never raises on odd data — unresolvable cases return PositionKind.NO_POSITION with
    an explanatory note, and the ETA engine degrades to its schedule-based fallback.
    """
    route = dedupe_route(route)
    if not route:
        return PositionResolution(PositionKind.NO_POSITION, PositionSource.UNKNOWN, None,
                                  notes=["Train has no route entries"])

    if latest_event is None:
        return PositionResolution(
            PositionKind.NO_POSITION, PositionSource.NO_EVENT, 0,
            last_known_station_code=None, next_station_code=route[0].station.station_code,
            notes=["No TrainEvent exists for this train — assuming journey not yet started"],
        )

    station_index = _route_index_by_station(route)

    # --- A: latest event is at a station -------------------------------------------
    if latest_event.station_id is not None:
        idx = station_index.get(latest_event.station_id)
        if idx is None:
            return PositionResolution(
                PositionKind.NO_POSITION, PositionSource.UNKNOWN, 0,
                last_known_station_code=route[0].station.station_code,
                notes=["Latest event references a station not on this train's route"],
            )
        station = route[idx].station
        if idx >= len(route) - 1:
            return PositionResolution(
                PositionKind.AT_STATION, PositionSource.LATEST_TRAIN_EVENT_STATION, None,
                last_known_station_code=station.station_code,
                notes=["Train is at its destination station"],
            )
        # A DEPARTURE event means the train has already left the station: it is (at
        # least) in the section towards the next stop. Any other event type at a
        # station counts as "at the station".
        if latest_event.event_type.value == "DEPARTURE":
            return PositionResolution(
                PositionKind.DEPARTED_STATION, PositionSource.LATEST_TRAIN_EVENT_STATION, idx + 1,
                current_section_entry_index=idx + 1, fraction_remaining_in_section=None,
                last_known_station_code=station.station_code,
                next_station_code=route[idx + 1].station.station_code,
                notes=["Latest event is a departure — progress within the next section is unknown"],
            )
        return PositionResolution(
            PositionKind.AT_STATION, PositionSource.LATEST_TRAIN_EVENT_STATION, idx + 1,
            last_known_station_code=station.station_code,
            next_station_code=route[idx + 1].station.station_code,
        )

    # --- B: latest event is inside a known railway section --------------------------
    if latest_event.section_id is not None:
        idx = next((i for i, entry in enumerate(route) if entry.section_id == latest_event.section_id), None)
        if idx is None:
            return PositionResolution(
                PositionKind.NO_POSITION, PositionSource.UNKNOWN, 0,
                last_known_station_code=route[0].station.station_code,
                notes=["Latest event references a section not on this train's route"],
            )
        return _section_resolution(latest_event, route, idx, source=PositionSource.LATEST_TRAIN_EVENT_SECTION)

    # --- C: GPS coordinates only -----------------------------------------------------
    if latest_event.latitude is not None and latest_event.longitude is not None:
        return _resolve_gps_only(latest_event, route, gps_station_proximity_km)

    # --- event with neither station, section, nor GPS -------------------------------
    return PositionResolution(
        PositionKind.NO_POSITION, PositionSource.UNKNOWN, 0,
        last_known_station_code=route[0].station.station_code,
        notes=["Latest event carries no station, section, or GPS position"],
    )


def _section_resolution(
    latest_event: TrainEvent, route: list[TrainRoute], dest_index: int, *, source: PositionSource
) -> PositionResolution:
    """Build a resolution for a train inside the section arriving at route[dest_index].

    Progress within the section uses GPS when available (straight-line projection — a
    documented Phase 5 approximation); without GPS the remaining distance is the full
    section (conservative: no position is fabricated).
    """
    entry = route[dest_index]
    station = entry.station
    fraction: float | None = None
    notes: list[str] = []

    if latest_event.latitude is not None and latest_event.longitude is not None and entry.section is not None:
        try:
            fraction = 1.0 - fraction_along_section(
                float(latest_event.latitude), float(latest_event.longitude),
                float(entry.section.from_station.latitude), float(entry.section.from_station.longitude),
                float(entry.section.to_station.latitude), float(entry.section.to_station.longitude),
            )
            notes.append("In-section progress approximated by projecting GPS onto the straight line "
                         "between the section's endpoint stations (no track geometry available)")
        except ValueError:
            notes.append("GPS coordinates invalid — full section distance assumed")

    return PositionResolution(
        PositionKind.IN_SECTION, source, dest_index,
        current_section_entry_index=dest_index, fraction_remaining_in_section=fraction,
        last_known_station_code=route[dest_index - 1].station.station_code if dest_index > 0 else None,
        next_station_code=station.station_code, notes=notes,
    )


def _resolve_gps_only(
    latest_event: TrainEvent, route: list[TrainRoute], proximity_km: float
) -> PositionResolution:
    """GPS with no station/section reference: resolve approximately.

    Strategy — nearest route station. Within `proximity_km` the train is considered AT
    that station; otherwise it is placed in the section between its two nearest
    consecutive route stations (resolved_current_section abstraction), with progress
    taken from the straight-line projection. All of this is labelled
    LATEST_TRAIN_EVENT_GPS / approximate — a Phase 5 limitation, not a GIS.
    """
    lat, lon = float(latest_event.latitude), float(latest_event.longitude)
    try:
        distances = [
            haversine_distance_km(lat, lon, float(e.station.latitude), float(e.station.longitude))
            for e in route
        ]
    except ValueError:
        return PositionResolution(
            PositionKind.NO_POSITION, PositionSource.UNKNOWN, 0,
            notes=["GPS coordinates invalid — cannot resolve position"],
        )

    nearest = min(range(len(route)), key=lambda i: distances[i])
    # Between the nearest station and one of its route neighbours? Pick the neighbour
    # that (with the nearest station) brackets the train's track-distance position.
    if distances[nearest] <= proximity_km:
        if nearest >= len(route) - 1:
            return PositionResolution(
                PositionKind.AT_STATION, PositionSource.LATEST_TRAIN_EVENT_GPS, None,
                last_known_station_code=route[nearest].station.station_code,
                notes=["GPS within proximity of the destination station"],
            )
        return PositionResolution(
            PositionKind.AT_STATION, PositionSource.LATEST_TRAIN_EVENT_GPS, nearest + 1,
            last_known_station_code=route[nearest].station.station_code,
            next_station_code=route[nearest + 1].station.station_code,
            notes=["GPS within station-proximity threshold — treated as AT_STATION"],
        )

    candidates = []
    for i in range(1, len(route)):
        if route[i].section_id is None:
            continue
        # Train between route[i-1] and route[i]: plausible if it is closer to this
        # pair than to any other pair — approximated by distance to the two endpoints.
        candidates.append((distances[i - 1] + distances[i], i))
    if not candidates:
        return PositionResolution(
            PositionKind.GPS_ONLY, PositionSource.LATEST_TRAIN_EVENT_GPS, 0,
            notes=["GPS position resolved but the route has no usable sections — assuming journey start"],
        )
    candidates.sort()
    dest_index = candidates[0][1]
    resolution = _section_resolution(latest_event, route, dest_index, source=PositionSource.LATEST_TRAIN_EVENT_GPS)
    resolution.kind = PositionKind.GPS_ONLY
    resolution.notes.append("Section assignment from nearest-endpoint heuristic — approximate")
    return resolution
