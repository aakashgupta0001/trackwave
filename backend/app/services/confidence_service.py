"""Prediction confidence (Phase 7): a transparent, configurable 0-100 score describing
confidence in the QUALITY of a prediction.

This is NOT a probability that the train arrives on time, and the level (HIGH/MEDIUM/
LOW) is not statistical likelihood — it is a weighted summary of data quality, model
quality, route quality, and prediction horizon. The factor model is deliberately
simple and deterministic: every factor's impact is returned so the score is fully
explainable and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings

# Additive factor weights (score starts at BASE and each factor adjusts it).
# RAILCAST model configuration — not a statistical calibration.
BASE_SCORE = 60.0

WEIGHT_FRESH_LIVE = 20.0        # fresh live/simulated state
WEIGHT_FRESH_STALE = -15.0      # stale state
WEIGHT_FRESH_UNAVAILABLE = -30.0  # no state at all
WEIGHT_POSITION_KNOWN = 10.0    # station/section/GPS position known
WEIGHT_POSITION_UNKNOWN = -10.0
WEIGHT_SECTION_KNOWN = 10.0     # real railway-section data for the current leg
WEIGHT_SECTION_UNKNOWN = -10.0
WEIGHT_ML_MODEL = 10.0          # fused with a loaded model
WEIGHT_ML_FALLBACK = -5.0       # baseline fallback (no ML correction)
WEIGHT_SUPPORT_STRONG = 10.0    # historical_support_score = 1.0 → ±WEIGHT_SUPPORT
WEIGHT_HORIZON_SHORT = 10.0     # horizon ≤ 30 min
WEIGHT_HORIZON_LONG = -10.0     # horizon ≥ CONFIDENCE_LONG_HORIZON_MINUTES

# Historical support: dataset rows needed for full support (linear below this).
SUPPORT_FULL_ROWS = 500
SUPPORT_DEFAULT_SCORE = 0.3  # conservative default when support is unknown

HORIZON_SHORT_MINUTES = 30.0


@dataclass
class ConfidenceFactor:
    factor: str
    impact: str  # POSITIVE / NEGATIVE / NEUTRAL

    def as_dict(self) -> dict:
        return {"factor": self.factor, "impact": self.impact}


@dataclass
class ConfidenceResult:
    score: int
    level: str
    factors: list[ConfidenceFactor] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level,
            "factors": [f.as_dict() for f in self.factors],
        }


def historical_support_score(dataset_rows: int | None) -> float:
    """Reusable 0-1 metric of how much historical data supports the model. Conservative
    default when unknown."""
    if dataset_rows is None or dataset_rows <= 0:
        return SUPPORT_DEFAULT_SCORE
    return min(1.0, dataset_rows / SUPPORT_FULL_ROWS)


def confidence_level(score: int) -> str:
    s = get_settings()
    if score >= s.CONFIDENCE_HIGH_THRESHOLD:
        return "HIGH"
    if score >= s.CONFIDENCE_MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _freshness_factor(data_status: str, event_age_seconds: float | None) -> tuple[float, ConfidenceFactor]:
    s = get_settings()
    if data_status in ("LIVE", "SIMULATED"):
        if event_age_seconds is None:
            return 0.0, ConfidenceFactor("LIVE_DATA_FRESHNESS", "NEUTRAL")
        if event_age_seconds <= s.CONFIDENCE_MAX_DATA_AGE_SECONDS:
            return WEIGHT_FRESH_LIVE, ConfidenceFactor("LIVE_DATA_FRESHNESS", "POSITIVE")
        # Configurable degradation: score decays linearly to zero at 3x the max age —
        # slightly old data is not punished to zero immediately.
        decay = max(0.0, WEIGHT_FRESH_LIVE * (1 - (event_age_seconds - s.CONFIDENCE_MAX_DATA_AGE_SECONDS) / (2 * s.CONFIDENCE_MAX_DATA_AGE_SECONDS)))
        return decay, ConfidenceFactor("LIVE_DATA_FRESHNESS", "NEUTRAL" if decay >= WEIGHT_FRESH_LIVE / 2 else "NEGATIVE")
    if data_status == "STALE":
        return WEIGHT_FRESH_STALE, ConfidenceFactor("LIVE_DATA_FRESHNESS", "NEGATIVE")
    return WEIGHT_FRESH_UNAVAILABLE, ConfidenceFactor("LIVE_DATA_FRESHNESS", "NEGATIVE")


def compute_confidence(
    *,
    data_status: str,
    event_age_seconds: float | None,
    position_known: bool,
    section_known: bool,
    model_available: bool,
    dataset_rows: int | None,
    baseline_minutes_ahead: float | None,
) -> ConfidenceResult:
    """Deterministic additive factor model. `baseline_minutes_ahead` is the prediction
    horizon (None = unknown, treated neutrally)."""
    factors: list[ConfidenceFactor] = []
    score = BASE_SCORE

    # Data quality
    delta, factor = _freshness_factor(data_status, event_age_seconds)
    score += delta
    factors.append(factor)

    delta = WEIGHT_POSITION_KNOWN if position_known else WEIGHT_POSITION_UNKNOWN
    score += delta
    factors.append(ConfidenceFactor("POSITION_KNOWN", "POSITIVE" if delta > 0 else "NEGATIVE"))

    delta = WEIGHT_SECTION_KNOWN if section_known else WEIGHT_SECTION_UNKNOWN
    score += delta
    factors.append(ConfidenceFactor("KNOWN_RAILWAY_SECTION", "POSITIVE" if delta > 0 else "NEGATIVE"))

    # Model quality
    if model_available:
        score += WEIGHT_ML_MODEL
        factors.append(ConfidenceFactor("ML_MODEL_AVAILABLE", "POSITIVE"))
    else:
        score += WEIGHT_ML_FALLBACK
        factors.append(ConfidenceFactor("ML_MODEL_AVAILABLE", "NEGATIVE"))

    support = historical_support_score(dataset_rows)
    delta = -WEIGHT_SUPPORT_STRONG + 2 * WEIGHT_SUPPORT_STRONG * support  # -W .. +W
    score += delta
    factors.append(
        ConfidenceFactor("HISTORICAL_SUPPORT", "POSITIVE" if support >= 0.5 else "NEGATIVE")
    )

    # Prediction horizon: short is better, degrades linearly to the long-horizon bound.
    horizon = baseline_minutes_ahead
    if horizon is not None and horizon == horizon:  # not NaN
        s = get_settings()
        if horizon <= HORIZON_SHORT_MINUTES:
            score += WEIGHT_HORIZON_SHORT
            factors.append(ConfidenceFactor("PREDICTION_HORIZON", "POSITIVE"))
        elif horizon >= s.CONFIDENCE_LONG_HORIZON_MINUTES:
            score += WEIGHT_HORIZON_LONG
            factors.append(ConfidenceFactor("PREDICTION_HORIZON", "NEGATIVE"))
        else:
            ratio = (horizon - HORIZON_SHORT_MINUTES) / (s.CONFIDENCE_LONG_HORIZON_MINUTES - HORIZON_SHORT_MINUTES)
            delta = WEIGHT_HORIZON_SHORT - 2 * WEIGHT_HORIZON_SHORT * ratio  # +W .. -W
            score += delta
            factors.append(ConfidenceFactor("PREDICTION_HORIZON", "NEUTRAL"))
    else:
        factors.append(ConfidenceFactor("PREDICTION_HORIZON", "NEUTRAL"))

    final = int(round(max(0, min(100, score))))
    return ConfidenceResult(score=final, level=confidence_level(final), factors=factors)
