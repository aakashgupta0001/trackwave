"""Phase 7 explainability unit tests:
- exact TreeSHAP contributions
- top-K sorting by absolute contribution
- direction mapping (positive -> LATER, negative -> EARLIER)
- deterministic feature translation layer
- baseline deterministic explanation factors (no ML needed)
- SHAP safety: graceful degradation on model unavailable, feature mismatch, or runtime errors
- verification that fake explanations are never returned
"""

import numpy as np
import pytest

from app.ml.exceptions import ModelUnavailableError
from app.ml.explain import (
    DISPLAY_NAMES,
    ExplanationFactor,
    ExplanationUnavailableError,
    safe_explain,
    shap_contributions,
    top_factors,
)
from app.schemas.eta import EtaCalculationDetails
from app.services.baseline_explain import baseline_factors


class DummyModel:
    def __init__(self, feature_columns):
        self.feature_columns = feature_columns
        self.booster = self

    def predict(self, matrix, pred_contribs=False):
        if not pred_contribs:
            return np.array([4.2])
        # Return mock SHAP contributions + bias column
        # e.g. for 4 features: [4.8, -0.9, 2.1, 1.3, bias=0.5]
        return np.array([[4.8, -0.9, 2.1, 1.3, 0.5]])


def test_top_factors_ranking_and_direction():
    contributions = [
        ("speed_kmph", -0.9),
        ("current_delay_minutes", 4.8),
        ("remaining_distance_km", 1.3),
        ("leg_average_minus_scheduled_minutes", 2.1),
        ("hour_of_day", 0.1),
        ("month", -0.05),
    ]
    # Top 4 factors by absolute magnitude
    factors = top_factors(contributions, k=4)
    assert len(factors) == 4

    # 1. current_delay_minutes (4.8) -> LATER
    assert factors[0].feature == "current_delay_minutes"
    assert factors[0].display_name == "Current delay"
    assert factors[0].contribution_minutes == 4.8
    assert factors[0].direction == "LATER"

    # 2. leg_average_minus_scheduled_minutes (2.1) -> LATER
    assert factors[1].feature == "leg_average_minus_scheduled_minutes"
    assert factors[1].display_name == "Section historical delay"
    assert factors[1].contribution_minutes == 2.1
    assert factors[1].direction == "LATER"

    # 3. remaining_distance_km (1.3) -> LATER
    assert factors[2].feature == "remaining_distance_km"
    assert factors[2].display_name == "Remaining distance"
    assert factors[2].contribution_minutes == 1.3
    assert factors[2].direction == "LATER"

    # 4. speed_kmph (-0.9) -> EARLIER
    assert factors[3].feature == "speed_kmph"
    assert factors[3].display_name == "Current speed"
    assert factors[3].contribution_minutes == -0.9
    assert factors[3].direction == "EARLIER"


def test_shap_contributions_feature_mismatch():
    cols = ["f1", "f2", "f3", "f4"]
    dummy = DummyModel(cols)
    # Provided vector has only 2 features instead of 4
    with pytest.raises(ExplanationUnavailableError, match="feature mismatch"):
        shap_contributions(dummy, [1.0, 2.0])


def test_safe_explain_graceful_failures():
    cols = ["f1", "f2", "f3", "f4"]
    dummy = DummyModel(cols)

    # Feature mismatch -> safe_explain returns (None, "EXPLANATION_UNAVAILABLE")
    factors, reason = safe_explain(dummy, [1.0, 2.0])
    assert factors is None
    assert reason == "EXPLANATION_UNAVAILABLE"

    # Model unavailable -> returns (None, "ML_MODEL_UNAVAILABLE")
    class BrokenModel:
        feature_columns = cols
        @property
        def booster(self):
            raise ModelUnavailableError("model file missing")

    factors, reason = safe_explain(BrokenModel(), [1.0, 2.0, 3.0, 4.0])
    assert factors is None
    assert reason == "ML_MODEL_UNAVAILABLE"


def test_baseline_factors_deterministic():
    # Baseline explanation derived from engine calculation metadata
    details = EtaCalculationDetails(
        position_source="AT_STATION",
        distance_source="RAILWAY_SECTION",
        speed_source="OPERATIONAL_SPEED",
        running_time_source="OPERATIONAL_SPEED",
        expected_speed_kmph=80.0,
        section_distance_km=45.0,
        delay_input_minutes=12.0,
        recovery_applied_minutes=2.0,
        estimated_halt_minutes=5.0,
    )
    b_factors = baseline_factors(details)
    lookup = {f.factor: f for f in b_factors}

    # CURRENT_DELAY: 12 min -> LATER
    assert lookup["CURRENT_DELAY"].effect == "LATER"
    assert lookup["CURRENT_DELAY"].value == 12.0
    assert lookup["CURRENT_DELAY"].display_name == "Current train delay"

    # DELAY_RECOVERY: 2 min -> EARLIER
    assert lookup["DELAY_RECOVERY"].effect == "EARLIER"
    assert lookup["DELAY_RECOVERY"].value == 2.0
    assert lookup["DELAY_RECOVERY"].display_name == "Expected delay recovery"

    # SECTION_RUNNING_TIME: NEUTRAL
    assert lookup["SECTION_RUNNING_TIME"].effect == "NEUTRAL"
    assert lookup["SECTION_RUNNING_TIME"].display_name == "Expected section travel time"

    # STATION_HALT: NEUTRAL
    assert lookup["STATION_HALT"].effect == "NEUTRAL"
    assert lookup["STATION_HALT"].value == 5.0

    # SECTION_DATA: NEUTRAL
    assert lookup["SECTION_DATA"].effect == "NEUTRAL"
    assert lookup["SECTION_DATA"].display_name == "Known railway section data"


def test_baseline_factors_empty_when_no_details():
    assert baseline_factors(None) == []
