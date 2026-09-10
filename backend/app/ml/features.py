"""Railway-aware feature engineering for the ML residual ETA model (Phase 6).

SINGLE SOURCE OF TRUTH: the same `build_feature_row` runs during dataset building
(offline, historical observations) and during real-time inference (fusion service), so
training and inference can never drift apart.

LEAKAGE RULE (critical): every input here must be known at the prediction timestamp.
No future arrival, future delay, future event of any kind is used. The optional
historical/rolling features (delay trend) are computed from an explicitly bounded list
of events that the caller must have restricted to `timestamp <= prediction time` —
the mandatory leakage regression test covers this.

Missing values become NaN (XGBoost handles them natively); categorical values are
encoded through a saved vocabulary (`CategoricalEncoder`) shared by training and
inference, with unseen categories mapping to a dedicated index.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.models.route import TrainRoute
from app.models.train import Train
from app.models.train_event import TrainEvent

# The complete, ordered feature list — also serialized into feature_schema.json so a
# trained model always travels with the exact columns it was trained on.
FEATURE_COLUMNS: list[str] = [
    # delay features
    "current_delay_minutes",
    "delay_trend_minutes",
    "speed_kmph",
    # position features
    "latitude",
    "longitude",
    # route features
    "distance_to_next_station_km",
    "remaining_distance_km",
    "remaining_sections",
    "remaining_stations",
    "route_progress_percent",
    # schedule / section features
    "leg_scheduled_running_minutes",
    "leg_average_running_minutes",
    "leg_average_minus_scheduled_minutes",
    "leg_speed_limit_kmph",
    "scheduled_halt_minutes",
    "baseline_delay_minutes",
    "baseline_minutes_ahead",
    # calendar features
    "hour_of_day",
    "day_of_week",
    "month",
    # categorical features (encoded)
    "train_type_encoded",
    "priority_encoded",
    "zone_encoded",
    "station_encoded",
    "section_encoded",
]

# Raw categorical column (as produced by build_feature_row) -> encoded column name.
RAW_CATEGORICAL_COLUMNS: list[str] = ["train_type", "priority", "zone", "station", "section"]
ENCODED_CATEGORICAL_MAP: dict[str, str] = {f"{c}_encoded": c for c in RAW_CATEGORICAL_COLUMNS}


class CategoricalEncoder:
    """Deterministic vocabulary encoding shared by training and inference.

    Values are assigned indices from a sorted vocabulary; unseen values (at inference
    or in validation) map to the reserved UNKNOWN index. The vocabulary is saved with
    the model (feature_schema.json) — encoding is never re-derived at inference time.
    """

    UNKNOWN = "__UNKNOWN__"

    def __init__(self, vocabularies: dict[str, list[str]] | None = None) -> None:
        # vocabularies: column -> sorted list of known raw values
        self.vocabularies: dict[str, dict[str, int]] = {}
        if vocabularies:
            for column, values in vocabularies.items():
                known = sorted(set(values) - {self.UNKNOWN})
                self.vocabularies[column] = {v: i for i, v in enumerate(known)}

    def fit(self, column: str, values: Sequence[str]) -> None:
        known = sorted({v for v in values if v is not None})
        self.vocabularies[column] = {v: i for i, v in enumerate(known)}

    def transform(self, column: str, value: str | None) -> float:
        vocabulary = self.vocabularies.get(column)
        if not vocabulary:
            return float("nan")
        if value is None or value not in vocabulary:
            return float(len(vocabulary))  # reserved UNKNOWN index
        return float(vocabulary[value])

    def to_dict(self) -> dict[str, list[str]]:
        return {col: sorted(mapping, key=mapping.get) for col, mapping in self.vocabularies.items()}

    @classmethod
    def from_dict(cls, payload: dict[str, list[str]]) -> "CategoricalEncoder":
        return cls(vocabularies=payload)


def fit_categorical_encoder(rows: list[dict[str, Any]]) -> "CategoricalEncoder":
    """Fit the categorical vocabulary from raw (pre-encoding) dataset rows."""
    encoder = CategoricalEncoder()
    for column in RAW_CATEGORICAL_COLUMNS:
        encoder.fit(column, [row.get(column) for row in rows if row.get(column) is not None])
    return encoder


@dataclass
class FeatureContext:
    """Everything needed to build one observation's features, all as of the prediction
    timestamp. Built by the dataset builder (offline) or the fusion service (online)
    from the baseline engine's outputs — never recomputed differently in either place.
    """

    train: Train
    latest_event: TrainEvent | None
    route: list[TrainRoute]  # full ordered route
    station_index: int  # route index of the station being predicted
    # The prediction timestamp itself (NOT the wall clock) — drives calendar features.
    prediction_time: datetime
    baseline_delay_minutes: float  # delay the baseline embedded in that station's ETA
    baseline_minutes_ahead: float  # (baseline_eta - now) in minutes; NaN when unknown
    remaining_distance_km: float
    remaining_sections: int
    remaining_stations: int
    route_progress_percent: float
    # Historical events at or before the prediction timestamp (bounded by the caller —
    # used only for the delay-trend feature).
    recent_events: list[TrainEvent] = field(default_factory=list)


def build_feature_row(ctx: FeatureContext) -> dict[str, float]:
    """One numeric feature row. Never raises on missing data — every field degrades to
    NaN, which XGBoost treats as missing."""
    entry = ctx.route[ctx.station_index]
    section = entry.section

    # LEAKAGE GUARD (defense in depth — callers must already bound history, but the
    # feature builder refuses to trust them): any event newer than the prediction
    # timestamp is invisible here, full stop.
    history = [e for e in ctx.recent_events if e.timestamp <= ctx.prediction_time]

    # Delay trend: change between the two most recent known delay observations.
    delays = [float(e.delay_minutes) for e in history if e.delay_minutes is not None]
    delay_trend = float("nan")
    if len(delays) >= 2:
        delay_trend = delays[0] - delays[1]  # newest first: positive = growing delay

    event = ctx.latest_event
    # hour comes from the timetable clock time; month/day-of-week from the prediction
    # timestamp (the run day) — a `time` object has no calendar month of its own.
    hour = dayofweek = month = float("nan")
    scheduled_arrival = entry.scheduled_arrival
    if scheduled_arrival is not None:
        hour = float(scheduled_arrival.hour)
    if ctx.prediction_time is not None:
        month = float(ctx.prediction_time.month)
        dayofweek = float(ctx.prediction_time.weekday())

    section_code = section.section_code if section is not None else None

    row: dict[str, float] = {
        "current_delay_minutes": float(event.delay_minutes) if event is not None and event.delay_minutes is not None else 0.0,
        "delay_trend_minutes": delay_trend,
        "speed_kmph": float(event.speed_kmph) if event is not None and event.speed_kmph is not None else float("nan"),
        "latitude": float(event.latitude) if event is not None and event.latitude is not None else float("nan"),
        "longitude": float(event.longitude) if event is not None and event.longitude is not None else float("nan"),
        "distance_to_next_station_km": float(section.distance_km) if section is not None and section.distance_km is not None else float("nan"),
        "remaining_distance_km": ctx.remaining_distance_km,
        "remaining_sections": float(ctx.remaining_sections),
        "remaining_stations": float(ctx.remaining_stations),
        "route_progress_percent": ctx.route_progress_percent,
        "leg_scheduled_running_minutes": float(section.scheduled_running_minutes) if section is not None and section.scheduled_running_minutes is not None else float("nan"),
        "leg_average_running_minutes": float(section.average_running_minutes) if section is not None and section.average_running_minutes is not None else float("nan"),
        "leg_average_minus_scheduled_minutes": (
            float(section.average_running_minutes) - float(section.scheduled_running_minutes)
            if section is not None
            and section.average_running_minutes is not None
            and section.scheduled_running_minutes is not None
            else float("nan")
        ),
        "leg_speed_limit_kmph": float(section.speed_limit_kmph) if section is not None and section.speed_limit_kmph is not None else float("nan"),
        "scheduled_halt_minutes": float(entry.halt_minutes or 0),
        "baseline_delay_minutes": ctx.baseline_delay_minutes,
        "baseline_minutes_ahead": ctx.baseline_minutes_ahead,
        "hour_of_day": hour,
        "day_of_week": dayofweek,
        "month": month,
        # Raw categoricals — encoded separately by `encode_row`.
        "train_type": ctx.train.train_type.value if hasattr(ctx.train.train_type, "value") else str(ctx.train.train_type),
        "priority": ctx.train.priority.value if hasattr(ctx.train.priority, "value") else str(ctx.train.priority),
        "zone": ctx.train.zone,
        "station": entry.station.station_code,
        "section": section_code,
    }
    return row


def encode_row(raw_row: Mapping[str, Any], encoder: CategoricalEncoder) -> dict[str, float]:
    """Convert a raw feature row into the final numeric vector with the exact
    FEATURE_COLUMNS ordering (raw categoricals replaced by their encoded values)."""
    encoded: dict[str, float] = {}
    for column in FEATURE_COLUMNS:
        if column in ENCODED_CATEGORICAL_MAP:
            encoded[column] = encoder.transform(ENCODED_CATEGORICAL_MAP[column], raw_row.get(ENCODED_CATEGORICAL_MAP[column]))
            continue
        value = raw_row.get(column)
        encoded[column] = float("nan") if value is None else float(value)
    return encoded


def row_to_vector(encoded_row: Mapping[str, float]) -> list[float]:
    """FEATURE_COLUMNS-ordered vector for XGBoost (list instead of DataFrame to avoid a
    pandas dependency at inference time)."""
    return [encoded_row[column] for column in FEATURE_COLUMNS]


def vector_is_finite_enough(encoded_row: Mapping[str, float], *, max_missing: int = 10) -> bool:
    """Sanity guard before inference: reject rows that are missing too much to be
    meaningful (the caller falls back to the baseline)."""
    missing = sum(1 for c in FEATURE_COLUMNS if (v := encoded_row.get(c)) is None or (isinstance(v, float) and math.isnan(v)))
    return missing <= max_missing
