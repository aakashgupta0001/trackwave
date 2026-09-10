"""Phase 6 ML tests — features, leakage prevention, dataset, model, evaluation,
fallback and fusion clamping. These run WITHOUT PostgreSQL or Redis; the synthetic
dataset generator is used directly and is deterministic (seeded).
"""

import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from app.ml import fallback as ml_fallback
from app.ml import features as feats
from app.ml.dataset import (
    DATASET_SOURCE,
    DATASET_SOURCE_SYNTHETIC,
    DATASET_TARGET,
    generate_synthetic_observations,
)
from app.ml.evaluation import comparison_table, regression_metrics
from app.ml.exceptions import ModelPredictionError, ModelUnavailableError
from app.ml.features import RAW_CATEGORICAL_COLUMNS as CATEGORICAL_COLUMNS, FEATURE_COLUMNS, build_feature_row, encode_row, row_to_vector
from app.ml.registry import ModelRegistry
from app.ml.target import residual_minutes

JOURNEY_DATE = date(2026, 9, 10)


# --- reuse the Phase 5 test fixtures' construction helpers -------------------------

def _station(code, name, lat, lon, id):
    from app.models.station import Station

    s = Station(station_code=code, station_name=name, latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)), zone="NR", station_type="MAJOR")
    s.id = id
    return s


@pytest.fixture
def mini_network():
    from app.models.enums import TrainPriority, TrainType
    from app.models.route import TrainRoute
    from app.models.section import RailwaySection
    from app.models.train import Train

    ndls = _station("NDLS", "New Delhi", 28.6432, 77.2196, 1)
    mtj = _station("MTJ", "Mathura Junction", 27.4924, 77.6737, 2)
    agc = _station("AGC", "Agra Cantt", 27.1591, 78.0092, 3)
    s1 = RailwaySection(id=11, section_code="NDLS-MTJ", from_station=ndls, to_station=mtj,
                        from_station_id=1, to_station_id=2, distance_km=Decimal("141"),
                        scheduled_running_minutes=95, average_running_minutes=100,
                        speed_limit_kmph=130, zone="NR")
    s2 = RailwaySection(id=12, section_code="MTJ-AGC", from_station=mtj, to_station=agc,
                        from_station_id=2, to_station_id=3, distance_km=Decimal("54"),
                        scheduled_running_minutes=40, average_running_minutes=42,
                        speed_limit_kmph=110, zone="NR")
    route = [
        TrainRoute(id=1, train_id=1, station_id=1, station=ndls, sequence_number=1,
                   scheduled_arrival=None, halt_minutes=0, distance_from_origin_km=Decimal("0")),
        TrainRoute(id=2, train_id=1, station_id=2, station=mtj, section=s1, section_id=11,
                   sequence_number=2, scheduled_arrival=time(10, 0), halt_minutes=5,
                   distance_from_origin_km=Decimal("141")),
        TrainRoute(id=3, train_id=1, station_id=3, station=agc, section=s2, section_id=12,
                   sequence_number=3, scheduled_arrival=time(11, 0), halt_minutes=0,
                   distance_from_origin_km=Decimal("195")),
    ]
    train = Train(id=1, train_number="T001", train_name="Test Express", train_type=TrainType.EXPRESS,
                  zone="NR", priority=TrainPriority.NORMAL, source_station_id=1,
                  destination_station_id=3, active=True)
    return train, route, {"NDLS": ndls, "MTJ": mtj, "AGC": agc, "s1": s1, "s2": s2}


def _event(**kwargs):
    from app.models.enums import EventSource, EventType
    from app.models.train_event import TrainEvent

    defaults = dict(train_id=1, timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
                    delay_minutes=0, event_type=EventType.DEPARTURE, event_source=EventSource.SIMULATOR)
    defaults.update(kwargs)
    return TrainEvent(**defaults)


def _ctx(mini_network, *, station_index=2, prediction_time=None, recent=None, latest=None):
    train, route, _ = mini_network
    prediction_time = prediction_time or datetime(2026, 9, 10, 9, 30, tzinfo=timezone.utc)
    return feats.FeatureContext(
        train=train, latest_event=latest or _event(delay_minutes=12), route=route,
        station_index=station_index, prediction_time=prediction_time,
        baseline_delay_minutes=13.5, baseline_minutes_ahead=90.0,
        remaining_distance_km=54.0, remaining_sections=1, remaining_stations=1,
        route_progress_percent=72.3, recent_events=recent or [],
    )


# --- feature generation --------------------------------------------------------------


def test_feature_generation_all_columns(mini_network):
    row = build_feature_row(_ctx(mini_network))
    # A RAW row carries every numeric feature plus every raw categorical (encoded
    # values are derived by encode_row, never stored raw).
    numeric = [c for c in FEATURE_COLUMNS if c not in feats.ENCODED_CATEGORICAL_MAP]
    assert set(row.keys()) >= set(numeric) | set(feats.RAW_CATEGORICAL_COLUMNS)
    assert row["current_delay_minutes"] == 12.0
    assert row["remaining_distance_km"] == 54.0
    assert row["leg_speed_limit_kmph"] == 110.0
    assert row["station"] == "AGC"
    assert row["train_type"] == "EXPRESS"


def test_feature_missing_values_become_nan(mini_network):
    row = build_feature_row(_ctx(mini_network, latest=_event(delay_minutes=None, speed_kmph=None)))
    assert math.isnan(row["speed_kmph"])
    assert row["current_delay_minutes"] == 0.0  # delay defaults to 0, not NaN
    assert math.isnan(row["latitude"])  # no GPS


def test_calendar_features_from_prediction_time_not_wall_clock(mini_network):
    t = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)  # a Monday
    row = build_feature_row(_ctx(mini_network, prediction_time=t))
    assert row["day_of_week"] == 0.0
    assert row["month"] == 9.0
    assert row["hour_of_day"] == 11.0  # scheduled arrival hour


def test_categorical_encoding_consistent_and_unknown_safe(mini_network):
    ctx = _ctx(mini_network)
    encoder = feats.fit_categorical_encoder([build_feature_row(ctx)])
    encoded = encode_row(build_feature_row(ctx), encoder)
    assert encoded["train_type_encoded"] == encoder.transform("train_type", "EXPRESS")
    # An unseen category maps to the reserved UNKNOWN index, never crashes:
    unseen = encode_row({**build_feature_row(ctx), "station": "ZZZ"}, encoder)
    assert unseen["station_encoded"] == encoder.transform("station", None)
    # Same input always encodes identically (train/inference consistency; NaN == NaN
    # for this purpose):
    again = encode_row(build_feature_row(ctx), encoder)
    for column in FEATURE_COLUMNS:
        a, b = encoded[column], again[column]
        assert (math.isnan(a) and math.isnan(b)) or a == b, column
    vector = row_to_vector(encoded)
    assert len(vector) == len(feats.FEATURE_COLUMNS)


# --- MANDATORY leakage regression test -------------------------------------------------


def test_no_future_information_in_features(mini_network):
    """Construct prediction timestamp T; add a historical record at T+1 with a wildly
    different delay. Feature generation for T MUST NOT see it."""
    T = datetime(2026, 9, 10, 9, 30, tzinfo=timezone.utc)
    past1 = _event(timestamp=T - timedelta(minutes=20), delay_minutes=10)
    past2 = _event(timestamp=T - timedelta(minutes=5), delay_minutes=12)
    future = _event(timestamp=T + timedelta(minutes=1), delay_minutes=999)

    baseline_ctx = _ctx(mini_network, prediction_time=T, recent=[past2, past1])
    # Simulate a buggy/unbounded caller passing the future event in: the feature
    # builder itself must ignore records after T.
    contaminated_ctx = _ctx(mini_network, prediction_time=T, recent=[future, past2, past1])

    row_clean = build_feature_row(baseline_ctx)
    row_contaminated = build_feature_row(contaminated_ctx)
    for column in FEATURE_COLUMNS:
        a, b = row_clean.get(column), row_contaminated.get(column)
        if isinstance(a, float) and isinstance(b, float):
            assert (math.isnan(a) and math.isnan(b)) or a == b, f"leak via {column}"


def test_dataset_generator_bounds_history_to_prediction_time(mini_network):
    """Regression test: the synthetic generator must never hand the feature builder an
    event newer than the observation's prediction timestamp."""
    captured = []
    import app.ml.dataset as ds

    original = ds.build_feature_row

    def spy(ctx):
        captured.append(ctx)
        return original(ctx)

    ds.build_feature_row = spy
    try:
        generate_synthetic_observations(days=2, seed=7)
    finally:
        ds.build_feature_row = original
    assert captured
    for ctx in captured:
        for event in ctx.recent_events:
            assert event.timestamp <= ctx.prediction_time


# --- dataset & target ------------------------------------------------------------------


def test_target_generation_signed():
    baseline = datetime(2026, 9, 10, 15, 20, tzinfo=timezone.utc)
    assert residual_minutes(datetime(2026, 9, 10, 15, 27, tzinfo=timezone.utc), baseline) == 7.0
    assert residual_minutes(datetime(2026, 9, 10, 15, 12, 30, tzinfo=timezone.utc), baseline) == -7.5


def test_synthetic_dataset_is_labelled_and_complete():
    observations = generate_synthetic_observations(days=2, seed=7)
    assert observations
    for obs in observations:
        assert obs.dataset_source == "SYNTHETIC"
        assert math.isfinite(obs.target_residual_minutes)
        assert obs.actual_arrival > obs.prediction_timestamp  # outcome after prediction


def test_chronological_split_never_leaks_forward():
    import pandas as pd

    from app.ml.training import chronological_split, validate_dataset

    observations = generate_synthetic_observations(days=6, seed=7)
    df = pd.DataFrame([obs.to_row() for obs in observations])
    validate_dataset(df)
    split = chronological_split(df)
    assert split.boundaries["method"] == "CHRONOLOGICAL_BY_JOURNEY_DAY"

    def day_range(part):
        days = pd.to_datetime(part["prediction_timestamp"]).dt.date
        return (days.min(), days.max())

    tr, va, te = day_range(split.train), day_range(split.validation), day_range(split.test)
    assert tr[1] <= va[0] and va[1] <= te[0]  # strictly forward in time
    assert split.train["prediction_timestamp"].max() <= split.validation["prediction_timestamp"].min()
    assert split.validation["prediction_timestamp"].max() <= split.test["prediction_timestamp"].min()


def test_validate_dataset_rejects_bad_input():
    import pandas as pd

    from app.ml.training import validate_dataset

    with pytest.raises(ValueError):
        validate_dataset(pd.DataFrame({"foo": [1]}))
    with pytest.raises(ValueError):
        validate_dataset(pd.DataFrame(columns=["irrelevant"]))


# --- model training / save / load / predict ---------------------------------------------


@pytest.fixture
def trained_model(tmp_path, monkeypatch):
    import pandas as pd

    from app.core.config import get_settings
    from app.ml.training import train_from_dataframe

    # Isolate the registry in a temp dir so tests never touch the real artifact.
    monkeypatch.setattr(get_settings(), "ML_MODEL_DIR", str(tmp_path / "models"))
    registry = ModelRegistry(tmp_path / "models")

    observations = generate_synthetic_observations(days=8, seed=11)
    df = pd.DataFrame([obs.to_row() for obs in observations])
    report = train_from_dataframe(df, version="test-v1", seed=11, register=True)
    return registry, report


def test_model_save_load_and_predict(tmp_path, mini_network, monkeypatch):
    """Train -> register -> load from disk -> predict must round-trip, producing a
    finite residual under the SAME feature schema."""
    import pandas as pd

    from app.ml.training import train_from_dataframe

    registry = ModelRegistry(tmp_path / "models")
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ML_MODEL_DIR", str(tmp_path / "models"))

    observations = generate_synthetic_observations(days=8, seed=11)
    df = pd.DataFrame([obs.to_row() for obs in observations])
    train_from_dataframe(df, version="roundtrip-v1", seed=11, register=True)

    loaded = registry.load("roundtrip-v1")
    assert loaded.version == "roundtrip-v1"
    assert loaded.feature_columns == FEATURE_COLUMNS
    assert loaded.metadata["dataset_source"] == "SYNTHETIC"

    import xgboost as xgb

    ctx = _ctx(mini_network)
    vector = row_to_vector(encode_row(build_feature_row(ctx), loaded.encoder))
    preds = loaded.booster.predict(xgb.DMatrix(np.asarray([vector], dtype=np.float32), feature_names=loaded.feature_columns))
    assert np.isfinite(preds[0])


def test_training_report_contains_comparison(trained_model):
    _, report = trained_model
    assert "comparison" in report
    assert report["comparison"]["ml_improves_over_baseline"] in {True, False}
    assert report["test_metrics"]["baseline"]["count"] == report["test_metrics"]["ml"]["count"]


def test_feature_schema_travels_with_model(trained_model):
    import json

    registry, _ = trained_model
    schema = json.loads((registry.model_dir("test-v1") / "feature_schema.json").read_text())
    assert schema["feature_columns"] == FEATURE_COLUMNS
    assert "train_type" in schema["categorical_vocabularies"]


# --- evaluation ---------------------------------------------------------------------------


def test_mae_rmse_metrics():
    m = regression_metrics(actual=[10.0, 20.0, 30.0], predicted=[12.0, 18.0, 33.0])
    assert m.mae == pytest.approx((2 + 2 + 3) / 3)
    assert m.mae <= m.rmse
    assert m.median_absolute_error == 2.0
    assert m.mean_error_bias == pytest.approx(1.0)


def test_baseline_comparison_reports_negative_improvement_honestly():
    worse = comparison_table(baseline_mae=5.0, ml_mae=7.0)
    assert worse["ml_improves_over_baseline"] is False
    assert worse["improvement_minutes"] == -2.0
    better = comparison_table(baseline_mae=7.0, ml_mae=5.0)
    assert better["ml_improves_over_baseline"] is True


# --- fallback -------------------------------------------------------------------------------


def test_safe_predict_falls_back_on_unavailable():
    def boom():
        raise ModelUnavailableError("No trained model available")

    outcome = ml_fallback.safe_predict(boom, None)
    assert not outcome.used_ml
    assert outcome.residual_minutes is None
    assert outcome.model_version is None
    assert outcome.reason in {ml_fallback.REASON_NO_MODEL, ml_fallback.REASON_DISABLED}


def test_safe_predict_falls_back_on_prediction_error():
    def boom():
        raise ModelPredictionError("bad features")

    outcome = ml_fallback.safe_predict(boom, "v1")
    assert outcome.reason == ml_fallback.REASON_PREDICTION_ERROR
    assert outcome.residual_minutes is None


def test_safe_predict_passes_value_through():
    outcome = ml_fallback.safe_predict(lambda: 4.2, "v1")
    assert outcome.used_ml and outcome.residual_minutes == 4.2 and outcome.reason is None


# --- residual clipping (fusion rule) ----------------------------------------------------------


def test_residual_clamping(monkeypatch):
    from app.services import eta_fusion_service as fusion

    settings = fusion.get_settings()
    monkeypatch.setattr(settings, "ML_RESIDUAL_MINUTES_MIN", -30.0)
    monkeypatch.setattr(settings, "ML_RESIDUAL_MINUTES_MAX", 60.0)

    used, clipped = fusion._clamp_residual(240.0)
    assert used == 60.0 and clipped is True
    used, clipped = fusion._clamp_residual(-120.0)
    assert used == -30.0 and clipped is True
    used, clipped = fusion._clamp_residual(6.5)
    assert used == 6.5 and clipped is False
