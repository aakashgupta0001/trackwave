"""Phase 7 uncertainty unit tests:
- empirical residual quantiles (P10/P90, asymmetric distributions)
- interval bounds and width
- empirical coverage & calibration metrics
- conditional horizon grouping and fallback to global quantiles
- insufficient data and missing metadata handling
"""

from datetime import datetime, timedelta, timezone
import pytest

from app.ml.uncertainty import (
    UNCERTAINTY_METHOD,
    build_uncertainty_metadata,
    calibrate_coverage,
    prediction_interval,
    residual_quantiles,
)


def test_residual_quantiles_symmetric():
    # Symmetric residuals around zero: -10 to +10
    residuals = list(range(-10, 11))
    q = residual_quantiles(residuals, level=0.80)
    assert q.sample_count == 21
    # 10th percentile and 90th percentile
    assert q.lower_quantile_value < 0
    assert q.upper_quantile_value > 0
    assert abs(abs(q.lower_quantile_value) - q.upper_quantile_value) < 1.0


def test_residual_quantiles_asymmetric():
    # Asymmetric distribution: skew towards positive delays (e.g. -2 to +18)
    residuals = [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 18.0]
    q = residual_quantiles(residuals, level=0.80)
    assert q.lower_quantile_value < 0
    assert q.upper_quantile_value > 10
    # Demonstrates asymmetric interval: upper bound magnitude > lower bound magnitude
    assert abs(q.upper_quantile_value) > abs(q.lower_quantile_value)


def test_prediction_interval_bounds_and_width():
    final_eta = datetime(2026, 9, 10, 15, 32, tzinfo=timezone.utc)
    meta = {
        "method": UNCERTAINTY_METHOD,
        "interval_level": 0.80,
        "global": {
            "lower_quantile_value_minutes": -5.0,
            "upper_quantile_value_minutes": 13.0,
            "sample_count": 100,
        },
    }
    interval = prediction_interval(meta, final_eta, baseline_minutes_ahead=45.0)
    assert interval.available is True
    assert interval.lower_eta == final_eta + timedelta(minutes=-5.0)  # 15:27
    assert interval.upper_eta == final_eta + timedelta(minutes=13.0)  # 15:45
    assert interval.interval_width_minutes == 18.0
    assert interval.interval_level == 0.80
    assert interval.source == "GLOBAL_QUANTILES"


def test_calibration_coverage_and_width():
    # 10 residuals: 8 inside [-5, +10], 2 outside
    residuals = [-8.0, -4.0, -2.0, 0.0, 1.0, 3.0, 5.0, 7.0, 9.0, 15.0]
    cal = calibrate_coverage(residuals, lower_value=-5.0, upper_value=10.0)
    # 8 out of 10 inside [-5, 10] -> 0.80 empirical coverage
    assert cal["coverage"] == 0.8
    assert cal["average_interval_width_minutes"] == 15.0
    assert cal["sample_count"] == 10


def test_insufficient_data_validation():
    with pytest.raises(ValueError, match="no residuals to quantify"):
        residual_quantiles([])

    with pytest.raises(ValueError, match="interval level must be in"):
        residual_quantiles([1.0, 2.0], level=1.5)

    with pytest.raises(ValueError, match="no residuals to calibrate"):
        calibrate_coverage([], -1.0, 1.0)


def test_build_uncertainty_metadata_and_conditional_buckets(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "UNCERTAINTY_MIN_GROUP_SIZE", 5)
    monkeypatch.setattr(get_settings(), "UNCERTAINTY_HORIZON_BUCKET_MINUTES", 30)

    # 10 residuals for horizon ~15m (bucket 0) and 3 for horizon ~45m (bucket 30, sparse)
    test_residuals = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0] + [10.0, 12.0, 14.0]
    horizons = [15.0] * 10 + [45.0] * 3

    meta = build_uncertainty_metadata(test_residuals, horizons)
    assert meta is not None
    assert meta["method"] == UNCERTAINTY_METHOD
    assert meta["interval_level"] == 0.80
    assert "0" in meta["conditional"]["buckets"]
    # Bucket "30" has only 3 samples, which is < min_group_size (5) -> pruned
    assert "30" not in meta["conditional"]["buckets"]

    # When querying for horizon 15m -> matches bucket 0
    final_eta = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    res_bucket = prediction_interval(meta, final_eta, baseline_minutes_ahead=15.0)
    assert res_bucket.available is True
    assert res_bucket.source == "HORIZON_BUCKET_QUANTILES"

    # When querying for horizon 45m -> bucket 30 was sparse, falls back to global
    res_fallback = prediction_interval(meta, final_eta, baseline_minutes_ahead=45.0)
    assert res_fallback.available is True
    assert res_fallback.source == "GLOBAL_QUANTILES"


def test_fallback_when_metadata_missing_or_incompatible():
    final_eta = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert prediction_interval(None, final_eta, 30.0).available is False
    assert prediction_interval(None, final_eta, 30.0).reason == "NO_UNCERTAINTY_METADATA"

    # Incompatible method name (e.g. from an old or unsupported format)
    incompatible = {"method": "UNKNOWN_METHOD", "global": {}}
    res = prediction_interval(incompatible, final_eta, 30.0)
    assert res.available is False
    assert res.reason == "NO_UNCERTAINTY_METADATA"

    # No final_eta
    assert prediction_interval({}, None, 30.0).available is False
    assert prediction_interval({}, None, 30.0).reason == "NO_FINAL_ETA"
