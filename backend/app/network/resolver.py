"""Converts a train's route (+ whatever delay is currently known) into estimated
section-occupancy windows — the raw material shared-section conflict detection and
propagation both work from.

Two builders, deliberately different in fidelity:

- `build_source_windows` — for the train whose delay we're propagating FROM. Reuses the
  already-computed Phase 5/6/7 final ETA per station (baseline + ML residual + recovery),
  so the source's windows carry the full engine's accuracy without reimplementing any of
  it here (module 30/31 of the Phase 8 spec).
- `build_schedule_windows` — for candidate/downstream trains. A much simpler model: the
  static timetable, uniformly shifted by that train's OWN currently-known delay (from its
  latest TrainEvent). Running the full ETA fusion engine for every candidate train in a
  graph walk would be expensive and isn't needed — we're checking whether the SOURCE
  train's delay pushes it into a candidate's *scheduled* window, which is exactly what
  the propagation model is for. This is a deliberate, documented approximation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.models.route import TrainRoute
from app.network.schemas import StopWindow


def scheduled_datetime(journey_date: date, clock_time: time | None, day_offset: int) -> datetime | None:
    """Absolute timestamp from a date-free timetable entry. Mirrors the convention used
    throughout the baseline ETA engine: clock times are treated as UTC (the seed data
    carries no timezone semantics), anchored at the train's origin departure date.
    """
    if clock_time is None:
        return None
    return datetime.combine(journey_date, clock_time, tzinfo=timezone.utc) + timedelta(days=day_offset)


def build_schedule_windows(
    route: list[TrainRoute], journey_date: date, delay_minutes: float = 0.0
) -> dict[int, StopWindow]:
    """One StopWindow per section the route uses, keyed by section_id. `delay_minutes`
    (typically the candidate train's own latest known delay) shifts both ends uniformly —
    no recovery model here, a conservative choice matching the "estimated" framing.
    """
    ordered = sorted(route, key=lambda r: r.sequence_number)
    windows: dict[int, StopWindow] = {}
    shift = timedelta(minutes=delay_minutes)

    for i in range(1, len(ordered)):
        prev_entry, entry = ordered[i - 1], ordered[i]
        if entry.section_id is None or entry.section is None:
            continue
        entry_time = scheduled_datetime(journey_date, prev_entry.scheduled_departure, prev_entry.day_offset)
        exit_time = scheduled_datetime(journey_date, entry.scheduled_arrival, entry.day_offset)
        if entry_time is None or exit_time is None:
            continue
        section = entry.section
        windows[entry.section_id] = StopWindow(
            section_id=entry.section_id,
            section_code=section.section_code,
            from_station_code=section.from_station.station_code,
            to_station_code=section.to_station.station_code,
            sequence_number=entry.sequence_number,
            entry_time=entry_time + shift,
            exit_time=exit_time + shift,
            delay_minutes=delay_minutes,
            is_estimated=delay_minutes != 0,
        )
    return windows


def build_source_windows(
    route: list[TrainRoute], final_eta_response, latest_event_timestamp: datetime | None = None
) -> dict[int, StopWindow]:
    """Windows for the source train's UPCOMING sections only, built from its already-fused
    final ETA per station (see module docstring). `final_eta_response` is a
    BaselineEtaResponse (Phase 5/6/7) — `.stations` is ordered, upcoming-only.

    Each station's `final_eta` is treated as the *exit* time of the section leading into
    it; the *entry* time is the previous upcoming station's final_eta, or — for the very
    first upcoming section — `latest_event_timestamp` (when the train was last actually
    observed there). Using the *analysis* time ("now") instead would be wrong whenever
    there's a gap between "when we last heard from this train" and "when someone happens
    to query this API" — exactly the case with sparse/simulated events, and it would
    silently balloon the first window to cover that entire gap. Falls back to the
    response's generation time only when no event exists at all (nothing better to use).
    This still slightly overstates each window by including halt time, which is the
    conservative direction for a decision-support tool.
    """
    ordered = sorted(route, key=lambda r: r.sequence_number)
    by_station_code = {r.station.station_code: r for r in ordered}

    windows: dict[int, StopWindow] = {}
    prev_time = latest_event_timestamp or final_eta_response.generated_at
    is_first = True
    for station in final_eta_response.stations:
        entry = by_station_code.get(station.station_code)
        if entry is None or entry.section_id is None or entry.section is None or station.final_eta is None:
            prev_time = station.final_eta or prev_time
            is_first = False
            continue
        section = entry.section

        entry_time = prev_time
        if is_first:
            # `prev_time` here is the latest event's own timestamp — real, but possibly
            # from a stale/different calendar day than `journey_date` in demo/seed data
            # (the event is real; "today" is whenever someone happens to query this
            # API). An event more than a few section-transits old would otherwise
            # balloon this window to spans of many hours. Clamp to a plausible
            # in-transit window: the section's own scheduled running time, ending at
            # the (correctly journey_date-anchored) exit time.
            max_span = timedelta(minutes=3 * section.scheduled_running_minutes)
            if station.final_eta - entry_time > max_span:
                entry_time = station.final_eta - timedelta(minutes=section.scheduled_running_minutes)
            is_first = False

        windows[entry.section_id] = StopWindow(
            section_id=entry.section_id,
            section_code=section.section_code,
            from_station_code=section.from_station.station_code,
            to_station_code=section.to_station.station_code,
            sequence_number=entry.sequence_number,
            entry_time=entry_time,
            exit_time=station.final_eta,
            delay_minutes=station.final_delay_minutes or 0.0,
            is_estimated=True,
        )
        prev_time = station.final_eta
    return windows
