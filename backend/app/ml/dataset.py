"""Dataset building for the ML residual ETA model (Phase 6).

Two sources, never mixed silently:

1. HISTORICAL — stored Prediction rows whose actual arrivals became known. Honest but
   currently (prototype seed data) empty; the builder reports insufficiency rather
   than pretending.

2. SYNTHETIC — a clearly-labelled generator for development/testing. It simulates
   many days of journeys over the REAL seeded network, then — crucially — produces
   every observation through the SAME baseline engine and feature builder used at
   inference time, so the ML layer trains on exactly the feature distribution it will
   see in production. A ground-truth latency process (rush-hour, day-of-week, train
   type effects + noise) creates residuals the baseline cannot explain but ML can
   learn. Nothing synthetic claims to represent real railway performance: every row
   and the metadata are tagged SYNTHETIC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import numpy as np

from app.ml.features import FEATURE_COLUMNS, RAW_CATEGORICAL_COLUMNS as CATEGORICAL_COLUMNS, FeatureContext, build_feature_row
from app.ml.target import (
    DATASET_SOURCE,
    DATASET_SOURCE_HISTORICAL,
    DATASET_SOURCE_SYNTHETIC,
    DATASET_TARGET,
    residual_minutes,
)
from app.services.baseline_eta_service import _scheduled_datetime, compute_baseline_eta
from app.services.position_resolver import dedupe_route

logger = logging.getLogger(__name__)

# Non-feature columns kept alongside the feature vector in the dataset.
METADATA_COLUMNS = [
    "train_number",
    "station_code",
    "prediction_timestamp",
    "scheduled_arrival",
    "baseline_eta",
    "actual_arrival",
    DATASET_TARGET,
    DATASET_SOURCE,
]


@dataclass
class Observation:
    raw_features: dict[str, Any]  # includes raw categorical values
    target_residual_minutes: float
    prediction_timestamp: datetime
    scheduled_arrival: datetime
    baseline_eta: datetime
    actual_arrival: datetime
    train_number: str
    station_code: str
    dataset_source: str

    def to_row(self) -> dict[str, Any]:
        row = {**self.raw_features}
        row.update(
            {
                DATASET_TARGET: self.target_residual_minutes,
                "prediction_timestamp": self.prediction_timestamp,
                "scheduled_arrival": self.scheduled_arrival,
                "baseline_eta": self.baseline_eta,
                "actual_arrival": self.actual_arrival,
                "train_number": self.train_number,
                "station_code": self.station_code,
                DATASET_SOURCE: self.dataset_source,
            }
        )
        return row


def dataframe_from_observations(observations: list[Observation]):
    import pandas as pd

    rows = [obs.to_row() for obs in observations]
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS + CATEGORICAL_COLUMNS + METADATA_COLUMNS)


# --------------------------------------------------------------------------------------
# SYNTHETIC generator — explicitly labelled, never presented as real-world performance
# --------------------------------------------------------------------------------------

def _build_network():
    """In-memory replica of the seeded Delhi→Mumbai sample network (same prototype
    values as scripts/seed.py), used so synthetic journeys exercise the real engine."""
    from scripts.seed import SECTIONS, STATIONS, TRAINS, _average_running_minutes

    from app.models.enums import StationType, TrainPriority, TrainType
    from app.models.route import TrainRoute
    from app.models.section import RailwaySection
    from app.models.station import Station
    from app.models.train import Train

    stations: dict[str, Station] = {}
    for i, data in enumerate(STATIONS, start=1):
        station = Station(
            id=i, station_code=data["station_code"], station_name=data["station_name"],
            latitude=Decimal(str(data["latitude"])), longitude=Decimal(str(data["longitude"])),
            zone=data["zone"], division=data["division"], state=data["state"],
            station_type=data["station_type"],
        )
        stations[data["station_code"]] = station

    sections_by_pair: dict[tuple[str, str], RailwaySection] = {}
    section_ids: dict[str, int] = {}
    for j, data in enumerate(SECTIONS, start=100):
        section = RailwaySection(
            id=j, section_code=data["section_code"],
            from_station=stations[data["from_station_code"]], to_station=stations[data["to_station_code"]],
            from_station_id=stations[data["from_station_code"]].id,
            to_station_id=stations[data["to_station_code"]].id,
            distance_km=Decimal(str(data["distance_km"])),
            scheduled_running_minutes=data["scheduled_running_minutes"],
            average_running_minutes=_average_running_minutes(data["scheduled_running_minutes"]),
            speed_limit_kmph=data["speed_limit_kmph"], zone=data["zone"],
        )
        sections_by_pair[(data["from_station_code"], data["to_station_code"])] = section
        section_ids[data["section_code"]] = j

    trains: list[tuple[Train, list[TrainRoute]]] = []
    for t, data in enumerate(TRAINS, start=10):
        train = Train(
            id=t, train_number=data["train_number"], train_name=data["train_name"],
            train_type=data["train_type"], zone=data["zone"], priority=data["priority"],
            source_station_id=stations[data["route"][0]].id,
            destination_station_id=stations[data["route"][-1]].id, active=True,
        )
        entries = _build_route_entries(stations, sections_by_pair, data["route"], data["origin_departure"], data["halt_minutes"])
        routes = []
        for k, entry in enumerate(entries, start=1):
            routes.append(
                TrainRoute(
                    id=(t * 100 + k), train_id=t, station_id=stations[entry["station_code"]].id,
                    station=stations[entry["station_code"]], section_id=entry["section_id"],
                    section=sections_by_pair.get(
                        (data["route"][k - 2], data["route"][k - 1]) if k >= 2 else None
                    ) if entry["section_id"] else None,
                    sequence_number=entry["sequence_number"], scheduled_arrival=entry["scheduled_arrival"],
                    scheduled_departure=entry["scheduled_departure"], day_offset=entry["day_offset"],
                    halt_minutes=entry["halt_minutes"],
                    distance_from_origin_km=Decimal(str(entry["distance_from_origin_km"])),
                )
            )
        trains.append((train, routes))

    return trains, stations


def _build_route_entries(stations, sections_by_pair, station_codes, origin_departure, halt_minutes):
    """Local copy of the seed script's timetable derivation (it operates on schema
    pydantic objects there; here we only need the plain values)."""
    entries: list[dict] = []
    elapsed = origin_departure.hour * 60 + origin_departure.minute
    cumulative = 0.0
    for i, code in enumerate(station_codes):
        is_origin, is_terminus = i == 0, i == len(station_codes) - 1
        section_id = None
        arrival = None
        if not is_origin:
            section = sections_by_pair[(station_codes[i - 1], code)]
            section_id = section.id
            elapsed += section.scheduled_running_minutes
            cumulative += float(section.distance_km)
            arrival_day, arrival_minute = divmod(elapsed, 24 * 60)
            arrival = time(hour=arrival_minute // 60, minute=arrival_minute % 60)
        departure = None
        halt = 0 if (is_origin or is_terminus) else halt_minutes
        if not is_terminus:
            if not is_origin:
                elapsed += halt_minutes
            departure_day, departure_minute = divmod(elapsed, 24 * 60)
            departure = time(hour=departure_minute // 60, minute=departure_minute % 60)
        entries.append(
            dict(station_code=code, section_id=section_id, sequence_number=i + 1,
                 scheduled_arrival=arrival, scheduled_departure=departure,
                 day_offset=elapsed // (24 * 60) if is_origin else arrival_day,
                 halt_minutes=halt, distance_from_origin_km=round(cumulative, 2))
        )
    return entries


def _ground_truth_extra_minutes(
    rng: np.random.Generator, scheduled_hour: int, weekday: int, train_type_value: str, current_delay: float
) -> float:
    """The latency process the baseline does NOT model — exactly the signal the ML
    residual model should be able to learn. Purely synthetic."""
    extra = float(rng.normal(0.0, 3.0))
    if 7 <= scheduled_hour < 10 or 17 <= scheduled_hour < 20:
        extra += 6.0  # rush-hour congestion
    if weekday == 0:
        extra += 3.0  # Monday effect
    type_effect = {"RAJDHANI": -2.0, "SHATABDI": -1.5, "SUPERFAST": 0.5, "EXPRESS": 1.0}
    extra += type_effect.get(train_type_value, 0.0)
    if current_delay > 10:
        extra += 0.1 * (current_delay - 10)  # late trains accumulate further
    return extra


def generate_synthetic_observations(
    days: int = 90, seed: int = 42, start_date: date | None = None
) -> list[Observation]:
    """Simulate `days` of journeys over the sample network and emit one observation per
    (train, day, upcoming station): features as known at the moment the train departs
    the previous stop, target = actual arrival - baseline ETA."""
    from app.models.enums import EventSource, EventType
    from app.models.train_event import TrainEvent

    rng = np.random.default_rng(seed)
    trains, _ = _build_network()
    start = start_date or (date.today() - timedelta(days=days))

    observations: list[Observation] = []
    for day_index in range(days):
        journey_date = start + timedelta(days=day_index)
        weekday = journey_date.weekday()
        for train, route in trains:
            route = dedupe_route(route)
            if len(route) < 2:
                continue
            departure_clock = route[0].scheduled_departure or time(0, 0)
            current_delay = float(np.clip(rng.normal(2.0, 6.0), -5.0, 45.0))
            recent_events: list[TrainEvent] = []

            for stop_index in range(1, len(route)):
                entry = route[stop_index]
                scheduled_arr = _scheduled_datetime(journey_date, entry.scheduled_arrival, entry.day_offset)
                if scheduled_arr is None:
                    continue

                # Prediction moment: the train departs the previous stop (scheduled
                # departure + current delay). Anchoring on the real departure keeps the
                # simulation physical — this stop's arrival is always later.
                prev_entry = route[stop_index - 1]
                prediction_time = _scheduled_datetime(
                    journey_date, prev_entry.scheduled_departure, prev_entry.day_offset
                ) + timedelta(minutes=current_delay)
                latest_event = recent_events[0] if recent_events else TrainEvent(
                    train_id=train.id, timestamp=prediction_time, delay_minutes=int(round(current_delay)),
                    event_type=EventType.DEPARTURE, event_source=EventSource.SIMULATOR, speed_kmph=Decimal("0"),
                )

                baseline = compute_baseline_eta(train, route, latest_event, journey_date, now=prediction_time)
                baseline_station = next(
                    (st for st in baseline.stations if st.station_code == entry.station.station_code), None
                )
                if baseline_station is None or baseline_station.baseline_eta is None:
                    # e.g. timetable gap forced a fallback walk that skipped this stop
                    pass_through = True
                else:
                    pass_through = False

                # Ground truth arrival for THIS stop.
                train_type_value = train.train_type.value if hasattr(train.train_type, "value") else str(train.train_type)
                extra = _ground_truth_extra_minutes(rng, scheduled_arr.hour, weekday, train_type_value, current_delay)
                current_delay = max(0.0, current_delay + extra)
                actual_arrival = scheduled_arr + timedelta(minutes=current_delay)

                if not pass_through:
                    raw_row = build_feature_row(
                        FeatureContext(
                            train=train,
                            latest_event=latest_event,
                            route=route,
                            station_index=stop_index,
                            prediction_time=prediction_time,
                            baseline_delay_minutes=baseline_station.delay_minutes,
                            baseline_minutes_ahead=(baseline_station.baseline_eta - prediction_time).total_seconds() / 60.0,
                            remaining_distance_km=baseline_station.remaining_distance_km,
                            remaining_sections=len(baseline.stations) - baseline.stations.index(baseline_station),
                            remaining_stations=len(baseline.stations) - baseline.stations.index(baseline_station),
                            route_progress_percent=100.0 * float(route[stop_index - 1].distance_from_origin_km)
                            / max(float(route[-1].distance_from_origin_km), 1e-6),
                            recent_events=list(recent_events),
                        )
                    )
                    observations.append(
                        Observation(
                            raw_features=raw_row,
                            target_residual_minutes=residual_minutes(actual_arrival, baseline_station.baseline_eta),
                            prediction_timestamp=prediction_time,
                            scheduled_arrival=scheduled_arr,
                            baseline_eta=baseline_station.baseline_eta,
                            actual_arrival=actual_arrival,
                            train_number=train.train_number,
                            station_code=entry.station.station_code,
                            dataset_source=DATASET_SOURCE_SYNTHETIC,
                        )
                    )

                # The event the NEXT stop's prediction will see (bounded by its
                # prediction time — no future information is ever used).
                recent_events.insert(
                    0,
                    TrainEvent(
                        train_id=train.id, timestamp=prediction_time,
                        delay_minutes=int(round(current_delay)), event_type=EventType.ARRIVAL,
                        event_source=EventSource.SIMULATOR, speed_kmph=Decimal("0"),
                        station_id=entry.station_id, station=entry.station,
                    ),
                )
                recent_events = recent_events[:2]  # keep only history ≤ prediction time

    logger.info(
        "Generated %d SYNTHETIC observations over %d days (seed=%d)", len(observations), days, seed
    )
    return observations


# --------------------------------------------------------------------------------------
# HISTORICAL source
# --------------------------------------------------------------------------------------


def count_historical_actual_arrivals(session) -> int:
    """How many stored predictions have a known outcome — the only way to build a real
    (non-synthetic) dataset today."""
    from sqlalchemy import func, select

    from app.models.prediction import Prediction

    return (
        session.execute(
            select(func.count()).select_from(Prediction).where(Prediction.actual_arrival.isnot(None))
        )
    ).scalar_one()
