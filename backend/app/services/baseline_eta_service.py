"""RAILCAST Baseline ETA Engine (Phase 5).

A deterministic, railway-aware ETA estimator — NOT an ML prediction. It walks the
train's remaining journey section by section, estimating each leg's running time from
the best available railway data and propagating the current delay with a conservative,
configurable recovery model:

    Latest Train State -> Position Resolver -> Remaining Route Resolver
        -> Section Travel-Time Estimator -> Station Halt Estimator
        -> Delay / Recovery Logic -> BASELINE ETA -> Baseline Prediction Object

Design rules (Phase 5 spec):
- Never `scheduled_arrival + current_delay` blindly: delay evolves per section with
  capped recovery, and section running times come from a data-quality hierarchy.
- FINAL ETA (Phase 6+) = BASELINE ETA + ML PREDICTED RESIDUAL. Nothing here computes
  an ml_correction — the engine stays fully independent of XGBoost/ML.
- Scheduled arrivals are never overwritten; baseline and scheduled always travel
  together so the ML residual has a well-defined target.

Expected-speed hierarchy per section (see `expected_speed_for_section`):
    1. operational/current speed (current leg only, where meaningful)
    2. section average running time   (SECTION_AVERAGE)
    3. scheduled running time         (SCHEDULE)
    4. speed limit                    (SPEED_LIMIT)
    5. configured fallback speed      (FALLBACK)
All speeds are clamped to [BASELINE_MIN_SPEED_KMPH, BASELINE_MAX_SPEED_KMPH].

Distance-source hierarchy (see `_leg_distance_km`):
    RailwaySection.distance_km -> route distance_from_origin_km deltas ->
    geographic approximation (explicitly labelled GEOGRAPHIC_APPROXIMATION).

Graceful degradation: any station whose timetable arrival is missing gets a
BASELINE_FALLBACK ETA reconstructed from cumulative travel-time estimates; with no
event at all the baseline equals the schedule (delay 0) with data_status=UNAVAILABLE.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache.redis import redis_client
from app.core.config import get_settings
from app.models.enums import EventSource, PredictionMode
from app.models.route import TrainRoute
from app.models.section import RailwaySection
from app.models.train import Train
from app.models.train_event import TrainEvent
from app.repositories import event_repository, station_repository
from app.schemas.eta import (
    BaselineEtaResponse,
    CurrentPosition,
    EtaCalculationDetails,
    EtaStation,
    SingleStationEtaResponse,
)
from app.services.exceptions import NotFoundError
from app.services.position_resolver import (
    PositionKind,
    PositionResolution,
    dedupe_route,
    resolve_position,
)
from app.utils.geo import haversine_distance_km

logger = logging.getLogger(__name__)

# Multiplier applied when the only available distance is the straight-line haversine
# distance: track distance is always longer, but this stays an explicitly-labelled
# approximation (GEOGRAPHIC_APPROXIMATION), never presented as railway distance.
GEOGRAPHIC_APPROXIMATION_FACTOR = 1.2

# Engine version stored on persisted Prediction rows. Deliberately NOT an ML model
# version — Phase 5 ships no ML.
BASELINE_MODEL_VERSION = "baseline-v1"


@dataclass
class SectionEstimate:
    """Internal result of `estimate_section_running_time` — also the raw material for
    explainability (future RailExplain input)."""

    distance_km: float
    expected_speed_kmph: float | None
    estimated_minutes: float
    method: str
    distance_source: str


def _clamp_speed(speed: float) -> float:
    s = get_settings()
    return max(s.BASELINE_MIN_SPEED_KMPH, min(s.BASELINE_MAX_SPEED_KMPH, speed))


def expected_speed_for_section(
    distance_km: float,
    section: RailwaySection | None,
    *,
    current_speed_kmph: float | None = None,
    is_current_leg: bool = False,
) -> tuple[float, str]:
    """Best available expected speed for a section, by the Phase 5 hierarchy.

    Returns (speed_kmph, method). The configured fallback guarantees a value, so the
    engine never divides by None and never assumes an unrealistic network-wide speed.
    """
    # 1. Operational/current speed: only meaningful for the leg the train is
    #    travelling right now, and only when it is actually moving.
    if is_current_leg and current_speed_kmph is not None and current_speed_kmph > 0:
        return _clamp_speed(current_speed_kmph), "OPERATIONAL_SPEED"

    if section is not None:
        # 2. Average running time + section distance.
        if section.average_running_minutes and section.average_running_minutes > 0:
            return _clamp_speed(distance_km / (section.average_running_minutes / 60.0)), "SECTION_AVERAGE"
        # 3. Scheduled running time + section distance.
        if section.scheduled_running_minutes and section.scheduled_running_minutes > 0:
            return _clamp_speed(distance_km / (section.scheduled_running_minutes / 60.0)), "SCHEDULE"
        # 4. Speed limit.
        if section.speed_limit_kmph and section.speed_limit_kmph > 0:
            return _clamp_speed(section.speed_limit_kmph), "SPEED_LIMIT"

    # 5. Configured fallback.
    return get_settings().BASELINE_FALLBACK_SPEED_KMPH, "FALLBACK"


def estimate_section_running_time(
    distance_km: float,
    section: RailwaySection | None,
    *,
    current_speed_kmph: float | None = None,
    is_current_leg: bool = False,
    distance_source: str = "RAILWAY_SECTION",
) -> SectionEstimate:
    """Estimated running minutes for one leg, with full method/distance provenance.

    Never returns a negative estimate: non-positive distance yields 0 minutes, and all
    speeds are clamped to plausible configured bounds.
    """
    if distance_km <= 0:
        return SectionEstimate(0.0, None, 0.0, "ZERO_DISTANCE", distance_source)

    speed, method = expected_speed_for_section(
        distance_km, section, current_speed_kmph=current_speed_kmph, is_current_leg=is_current_leg
    )
    minutes = max(0.0, 60.0 * distance_km / speed)
    return SectionEstimate(
        distance_km=round(distance_km, 3),
        expected_speed_kmph=round(speed, 2),
        estimated_minutes=round(minutes, 2),
        method=method,
        distance_source=distance_source,
    )


# --------------------------------------------------------------------------------------
# Input loading
# --------------------------------------------------------------------------------------


async def _load_route(session: AsyncSession, train_id: int) -> list[TrainRoute]:
    """The train's full route in one query, with everything the engine touches
    eager-loaded (station identity + each section's endpoint stations) — no N+1 while
    walking the remaining journey."""
    result = await session.execute(
        select(TrainRoute)
        .where(TrainRoute.train_id == train_id)
        .options(
            selectinload(TrainRoute.station),
            selectinload(TrainRoute.section).selectinload(RailwaySection.from_station),
            selectinload(TrainRoute.section).selectinload(RailwaySection.to_station),
        )
        .order_by(TrainRoute.sequence_number)
    )
    return list(result.scalars().all())


async def load_engine_inputs(
    session: AsyncSession, train_number: str
) -> tuple[Train, list[TrainRoute], TrainEvent | None]:
    """Everything the engine needs for one train: three queries total, regardless of
    route length (train, route, latest event)."""
    result = await session.execute(
        select(Train)
        .where(Train.train_number == train_number)
        .options(selectinload(Train.source_station), selectinload(Train.destination_station))
    )
    train = result.scalar_one_or_none()
    if train is None:
        raise NotFoundError(f"Train {train_number} not found")
    route = await _load_route(session, train.id)
    latest_event = await event_repository.get_latest_for_train(session, train.id)
    return train, route, latest_event


# --------------------------------------------------------------------------------------
# Pure computation
# --------------------------------------------------------------------------------------


def _scheduled_datetime(journey_date: date, arrival: time | None, day_offset: int) -> datetime | None:
    """Absolute scheduled timestamp from the date-free timetable template.

    Schedule clock times are interpreted as UTC in this prototype (the seed data carries
    no timezone semantics); the anchor is journey_date = the origin departure date.
    """
    if arrival is None:
        return None
    return datetime.combine(journey_date, arrival, tzinfo=timezone.utc) + timedelta(days=day_offset)


def _leg_distance_km(route: list[TrainRoute], target_index: int) -> tuple[float, str]:
    """Railway distance of the leg ending at route[target_index], by the distance
    hierarchy: section row -> route distance metadata -> geographic approximation."""
    if target_index == 0:
        return 0.0, "ORIGIN"
    entry = route[target_index]
    if entry.section is not None and entry.section.distance_km is not None:
        return float(entry.section.distance_km), "RAILWAY_SECTION"
    prev = route[target_index - 1]
    delta = float(entry.distance_from_origin_km) - float(prev.distance_from_origin_km)
    if delta > 0:
        return delta, "ROUTE_DISTANCE_METADATA"
    try:
        straight = haversine_distance_km(
            float(prev.station.latitude), float(prev.station.longitude),
            float(entry.station.latitude), float(entry.station.longitude),
        )
        return round(straight * GEOGRAPHIC_APPROXIMATION_FACTOR, 3), "GEOGRAPHIC_APPROXIMATION"
    except ValueError:
        return 0.0, "UNAVAILABLE"


def _recovery_minutes(delay: float) -> float:
    """CONFIGURED_BASELINE_RECOVERY: how much of the current delay the baseline allows
    the train to claw back over one section. Deliberately conservative and capped both
    relatively (percent of current delay) and absolutely (minutes per section) — a
    train never instantly returns to schedule. These are RAILCAST model configuration
    values, not Indian Railways operating rules."""
    s = get_settings()
    if delay <= 0:
        return 0.0
    return round(min(delay * s.BASELINE_MAX_RECOVERY_PERCENT / 100.0, s.BASELINE_MAX_RECOVERY_MINUTES_PER_SECTION), 2)


def _data_status_for_event(event: TrainEvent | None) -> tuple[str | None, str]:
    """(data_source, data_status) from the origin and freshness of the latest event.

    A stale event still yields a computed ETA — honestly labelled STALE, never
    pretending to be live."""
    s = get_settings()
    if event is None:
        return None, "UNAVAILABLE"
    source = event.event_source.value if isinstance(event.event_source, EventSource) else str(event.event_source)
    age_minutes = (datetime.now(timezone.utc) - event.timestamp).total_seconds() / 60.0
    if age_minutes > s.BASELINE_STALE_STATE_MINUTES:
        return source, "STALE"
    if source == EventSource.SIMULATOR.value:
        return source, "SIMULATED"
    return source, "LIVE"


def compute_baseline_eta(
    train: Train,
    route_raw: list[TrainRoute],
    latest_event: TrainEvent | None,
    journey_date: date,
    *,
    now: datetime | None = None,
) -> BaselineEtaResponse:
    """Deterministically compute the baseline ETA for every upcoming station (including
    the destination). Pure function of its arguments — no I/O — so it is directly
    unit-testable and safely cacheable."""
    now = now or datetime.now(timezone.utc)
    route = dedupe_route(route_raw)
    resolution: PositionResolution = resolve_position(latest_event, route)

    data_source, data_status = _data_status_for_event(latest_event)
    initial_delay = max(0.0, float(latest_event.delay_minutes)) if latest_event is not None else 0.0
    current_speed = (
        float(latest_event.speed_kmph)
        if latest_event is not None and latest_event.speed_kmph is not None
        else None
    )

    first_idx = resolution.first_upcoming_index
    upcoming = route[first_idx:] if first_idx is not None else []

    stations: list[EtaStation] = []
    delay = initial_delay
    cumulative_distance = 0.0
    cumulative_fallback_minutes = 0.0
    total_recovery = 0.0
    in_fallback = False
    methods_used: set[str] = set()
    notes: list[str] = list(resolution.notes)

    for offset, entry in enumerate(upcoming):
        leg_index = first_idx + offset
        is_current_leg = offset == 0
        recovery = 0.0

        raw_distance, distance_source = _leg_distance_km(route, leg_index)

        # Partial remaining distance when the train is inside this leg's section right now.
        fraction = 1.0
        if (
            is_current_leg
            and resolution.current_section_entry_index == leg_index
            and resolution.kind in (PositionKind.IN_SECTION, PositionKind.GPS_ONLY, PositionKind.DEPARTED_STATION)
        ):
            if resolution.fraction_remaining_in_section is not None:
                fraction = resolution.fraction_remaining_in_section
            # DEPARTED_STATION / in-section without GPS: fraction stays 1.0 — the full
            # section is used because no position within it can be established
            # (documented Phase 5 limitation, never a fabricated midpoint).

        leg_distance = round(raw_distance * fraction, 3)
        estimate = estimate_section_running_time(
            leg_distance,
            entry.section,
            current_speed_kmph=current_speed if is_current_leg else None,
            is_current_leg=is_current_leg,
            distance_source=distance_source,
        )
        methods_used.add(estimate.method)

        scheduled_dt = _scheduled_datetime(journey_date, entry.scheduled_arrival, entry.day_offset)
        halt_minutes = float(entry.halt_minutes or 0)
        cumulative_distance += leg_distance

        if scheduled_dt is None and leg_index == 0:
            # The origin stop has no arrival time and no preceding leg — there is no
            # arrival to estimate, so skip it without forcing the whole journey into
            # the fallback walk.
            continue

        if scheduled_dt is not None and not in_fallback:
            # Section-aware path: the delay evolves per remaining section instead of
            # being copied forward unchanged.
            sched_leg_minutes = (
                float(entry.section.scheduled_running_minutes or 0) * fraction
                if entry.section is not None
                else 0.0
            )
            deviation = round(estimate.estimated_minutes - sched_leg_minutes, 2)
            recovery = _recovery_minutes(delay)
            delay = round(max(0.0, delay + deviation - recovery), 2)
            total_recovery += recovery
            baseline_dt = scheduled_dt + timedelta(minutes=delay)
            mode = PredictionMode.BASELINE
        else:
            # BASELINE_FALLBACK: no timetable anchor for this station (or an earlier
            # one already forced the fallback walk) — reconstruct from cumulative
            # travel time from now. Halts of intermediate stations passed en route are
            # included (the halt estimator is deliberately swappable later for
            # historical dwell prediction without touching this engine's structure).
            in_fallback = True
            if offset > 0:
                cumulative_fallback_minutes += float(upcoming[offset - 1].halt_minutes or 0)
            elif resolution.kind == PositionKind.AT_STATION and leg_index > 0:
                # The train is still at the previous station: its scheduled halt
                # elapses before the run to this station begins.
                cumulative_fallback_minutes += float(route[leg_index - 1].halt_minutes or 0)
            cumulative_fallback_minutes += estimate.estimated_minutes
            baseline_dt = now + timedelta(minutes=cumulative_fallback_minutes)
            mode = PredictionMode.BASELINE_FALLBACK

        delay_out = 0.0
        if baseline_dt is not None and scheduled_dt is not None:
            delay_out = round(max(0.0, (baseline_dt - scheduled_dt).total_seconds() / 60.0), 2)

        stations.append(
            EtaStation(
                station_code=entry.station.station_code,
                station_name=entry.station.station_name,
                sequence_number=entry.sequence_number,
                scheduled_arrival=scheduled_dt,
                baseline_eta=baseline_dt,
                delay_minutes=delay_out,
                remaining_distance_km=round(cumulative_distance, 3),
                prediction_mode=mode,
                calculation_details=EtaCalculationDetails(
                    position_source=resolution.position_source.value,
                    distance_source=distance_source,
                    speed_source=estimate.method,
                    running_time_source=estimate.method,
                    expected_speed_kmph=estimate.expected_speed_kmph,
                    section_distance_km=leg_distance,
                    delay_input_minutes=initial_delay,
                    recovery_applied_minutes=recovery,
                    estimated_halt_minutes=0.0 if offset == len(upcoming) - 1 else halt_minutes,
                ),
            )
        )

    position = CurrentPosition(
        kind=resolution.kind.value,
        position_source=resolution.position_source.value,
        station_code=(
            latest_event.station.station_code
            if latest_event is not None and latest_event.station is not None
            else None
        ),
        section_code=(
            latest_event.section.section_code
            if latest_event is not None and latest_event.section is not None
            else None
        ),
        last_known_station_code=resolution.last_known_station_code,
        next_station_code=resolution.next_station_code,
    )

    engine_details = {
        "calculation_method": "SECTION_AWARE_WITH_FALLBACK" if in_fallback else "SECTION_AWARE",
        "position_source": resolution.position_source.value,
        "distance_source": (
            "RAILWAY_SECTION"
            if any(st.calculation_details.distance_source == "RAILWAY_SECTION" for st in stations)
            else "MIXED"
        ),
        "speed_sources": sorted(methods_used),
        "delay_input_minutes": initial_delay,
        "recovery_applied_minutes": round(total_recovery, 2),
        "remaining_sections": len(upcoming),
        "remaining_distance_km": round(cumulative_distance, 3),
        "recovery_model": "CONFIGURED_BASELINE_RECOVERY",
        "at_destination": latest_event is not None and first_idx is None,
        "notes": notes,
    }

    return BaselineEtaResponse(
        train_number=train.train_number,
        train_name=train.train_name,
        generated_at=now,
        journey_date=journey_date,
        prediction_mode=PredictionMode.BASELINE,
        data_source=data_source,
        data_status=data_status,  # type: ignore[arg-type]
        current_position=position,
        remaining_distance_km=round(cumulative_distance, 3),
        stations=stations,
        calculation_details=engine_details,
    )


# --------------------------------------------------------------------------------------
# Cached + persisting service entry points
# --------------------------------------------------------------------------------------


def _cache_key(train_number: str, latest_event: TrainEvent | None) -> str:
    # State-versioned: when the train's latest event changes, the key changes, so a new
    # state can never be served an old ETA. The short TTL bounds serving further.
    state_token = latest_event.timestamp.isoformat() if latest_event is not None else "no-event"
    return f"railcast:baseline_eta:{train_number}:{state_token}"


async def _read_cache(key: str) -> dict | None:
    try:
        raw = await redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("Redis unavailable reading baseline ETA cache key=%s", key, exc_info=True)
        return None


async def _write_cache(key: str, payload: dict) -> None:
    try:
        await redis_client.set(key, json.dumps(payload, default=str), ex=get_settings().BASELINE_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis unavailable writing baseline ETA cache key=%s", key, exc_info=True)


async def get_baseline_eta(
    session: AsyncSession, train_number: str, journey_date: date | None = None, *, use_cache: bool = True
) -> BaselineEtaResponse:
    """Baseline ETAs for all upcoming stations (cache-first), persisting fresh
    Prediction rows best-effort on cache misses."""
    train, route, latest_event = await load_engine_inputs(session, train_number)
    journey_date = journey_date or date.today()
    key = _cache_key(train.train_number, latest_event)

    if use_cache:
        cached = await _read_cache(key)
        if cached is not None:
            try:
                return BaselineEtaResponse.model_validate(cached)
            except Exception:
                logger.warning("Discarding unreadable baseline ETA cache entry key=%s", key)

    response = compute_baseline_eta(train, route, latest_event, journey_date)
    await _write_cache(key, response.model_dump(mode="json"))
    await _persist_predictions(session, train, response)
    return response


async def get_station_eta(
    session: AsyncSession, train_number: str, station_code: str, journey_date: date | None = None
) -> SingleStationEtaResponse:
    """Baseline ETA for one specific upcoming station."""
    code = station_code.upper()
    response = await get_baseline_eta(session, train_number, journey_date)
    match = next((st for st in response.stations if st.station_code == code), None)
    if match is None:
        station = await station_repository.get_by_code(session, code)
        if station is None:
            raise NotFoundError(f"Station {code} not found")
        raise NotFoundError(
            f"Station {code} is not an upcoming stop for train {train_number} "
            "(already passed, at destination, or not on the route)"
        )
    return SingleStationEtaResponse(
        train_number=response.train_number,
        station_code=match.station_code,
        station_name=match.station_name,
        scheduled_arrival=match.scheduled_arrival,
        baseline_eta=match.baseline_eta,
        delay_minutes=match.delay_minutes,
        remaining_distance_km=match.remaining_distance_km,
        prediction_mode=match.prediction_mode,
        data_source=response.data_source,
        data_status=response.data_status,
        calculation_details=match.calculation_details,
    )


async def _persist_predictions(session: AsyncSession, train: Train, response: BaselineEtaResponse) -> None:
    """Best-effort persistence of fresh baseline predictions as Prediction rows
    (prediction_mode=BASELINE / BASELINE_FALLBACK, ml_correction left null). Failures
    are logged, never raised — the predictions table must not take the ETA API down."""
    from app.repositories import prediction_repository

    try:
        for station in response.stations:
            await prediction_repository.upsert_baseline(
                session,
                train_id=train.id,
                station_code=station.station_code,
                prediction_timestamp=response.generated_at,
                scheduled_eta=station.scheduled_arrival,
                baseline_eta=station.baseline_eta,
                prediction_mode=station.prediction_mode,
                model_version=BASELINE_MODEL_VERSION,
            )
        await session.commit()
    except Exception:
        logger.warning("Failed to persist baseline predictions for train %s", train.train_number, exc_info=True)
        await session.rollback()
