"""Phase 7 confidence unit tests:
- fresh live data vs stale data vs unavailable data freshness degradation
- known section vs unknown section
- known position vs unknown position
- strong historical support vs sparse support
- short horizon vs long horizon degradation
- score boundaries (0-100 clamping)
- HIGH, MEDIUM, LOW levels and configurable thresholds
"""

import pytest
from app.core.config import get_settings
from app.services.confidence_service import (
    compute_confidence,
    confidence_level,
    historical_support_score,
)


def test_confidence_level_mapping(monkeypatch):
    monkeypatch.setattr(get_settings(), "CONFIDENCE_HIGH_THRESHOLD", 80)
    monkeypatch.setattr(get_settings(), "CONFIDENCE_MEDIUM_THRESHOLD", 50)

    assert confidence_level(100) == "HIGH"
    assert confidence_level(80) == "HIGH"
    assert confidence_level(79) == "MEDIUM"
    assert confidence_level(50) == "MEDIUM"
    assert confidence_level(49) == "LOW"
    assert confidence_level(0) == "LOW"


def test_historical_support_score():
    assert historical_support_score(None) == 0.3  # conservative default
    assert historical_support_score(0) == 0.3
    assert historical_support_score(-10) == 0.3
    assert historical_support_score(250) == 0.5   # 250 / 500
    assert historical_support_score(500) == 1.0
    assert historical_support_score(1000) == 1.0  # capped at 1.0


def test_confidence_fresh_live_data_high_score():
    # Fresh data (30s old), position & section known, ML active, full support, short horizon
    res = compute_confidence(
        data_status="LIVE",
        event_age_seconds=30.0,
        position_known=True,
        section_known=True,
        model_available=True,
        dataset_rows=500,
        baseline_minutes_ahead=20.0,
    )
    assert res.score >= 80
    assert res.level == "HIGH"
    factors = {f.factor: f.impact for f in res.factors}
    assert factors["LIVE_DATA_FRESHNESS"] == "POSITIVE"
    assert factors["POSITION_KNOWN"] == "POSITIVE"
    assert factors["KNOWN_RAILWAY_SECTION"] == "POSITIVE"
    assert factors["ML_MODEL_AVAILABLE"] == "POSITIVE"
    assert factors["HISTORICAL_SUPPORT"] == "POSITIVE"
    assert factors["PREDICTION_HORIZON"] == "POSITIVE"


def test_confidence_freshness_degradation():
    # Fresh vs slightly aged vs stale vs unavailable (using non-saturating baseline)
    fresh = compute_confidence(
        data_status="LIVE",
        event_age_seconds=60.0,
        position_known=True,
        section_known=False,
        model_available=True,
        dataset_rows=200,
        baseline_minutes_ahead=40.0,
    )
    aged = compute_confidence(
        data_status="LIVE",
        event_age_seconds=240.0,  # between max_age (120) and 3x max_age (360)
        position_known=True,
        section_known=False,
        model_available=True,
        dataset_rows=200,
        baseline_minutes_ahead=40.0,
    )
    stale = compute_confidence(
        data_status="STALE",
        event_age_seconds=1800.0,
        position_known=True,
        section_known=False,
        model_available=True,
        dataset_rows=200,
        baseline_minutes_ahead=40.0,
    )
    unavailable = compute_confidence(
        data_status="UNAVAILABLE",
        event_age_seconds=None,
        position_known=False,
        section_known=False,
        model_available=False,
        dataset_rows=None,
        baseline_minutes_ahead=None,
    )

    assert fresh.score > aged.score > stale.score > unavailable.score
    assert stale.score < 80
    assert unavailable.level == "LOW"


def test_confidence_horizon_degradation():
    # Short horizon (15 min) vs Long horizon (180 min)
    short_h = compute_confidence(
        data_status="LIVE",
        event_age_seconds=30.0,
        position_known=True,
        section_known=False,
        model_available=True,
        dataset_rows=200,
        baseline_minutes_ahead=15.0,
    )
    long_h = compute_confidence(
        data_status="LIVE",
        event_age_seconds=30.0,
        position_known=True,
        section_known=False,
        model_available=True,
        dataset_rows=200,
        baseline_minutes_ahead=180.0,
    )
    assert short_h.score > long_h.score
    factors_short = {f.factor: f.impact for f in short_h.factors}
    factors_long = {f.factor: f.impact for f in long_h.factors}
    assert factors_short["PREDICTION_HORIZON"] == "POSITIVE"
    assert factors_long["PREDICTION_HORIZON"] == "NEGATIVE"


def test_confidence_score_boundaries_clamping():
    # Maximum possible score is capped at 100
    high_all = compute_confidence(
        data_status="LIVE",
        event_age_seconds=10.0,
        position_known=True,
        section_known=True,
        model_available=True,
        dataset_rows=5000,
        baseline_minutes_ahead=5.0,
    )
    assert high_all.score == 100
    assert high_all.level == "HIGH"

    # Minimum possible score is capped at 0
    low_all = compute_confidence(
        data_status="UNAVAILABLE",
        event_age_seconds=None,
        position_known=False,
        section_known=False,
        model_available=False,
        dataset_rows=0,
        baseline_minutes_ahead=200.0,
    )
    assert low_all.score >= 0
    assert low_all.level == "LOW"


def test_confidence_section_and_model_fallbacks():
    unknown_section = compute_confidence(
        data_status="LIVE",
        event_age_seconds=30.0,
        position_known=True,
        section_known=False,
        model_available=False,
        dataset_rows=None,
        baseline_minutes_ahead=60.0,
    )
    factors = {f.factor: f.impact for f in unknown_section.factors}
    assert factors["KNOWN_RAILWAY_SECTION"] == "NEGATIVE"
    assert factors["ML_MODEL_AVAILABLE"] == "NEGATIVE"
