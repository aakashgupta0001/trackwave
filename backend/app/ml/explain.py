"""SHAP explainability for the XGBoost residual model (Phase 7).

Implementation: XGBoost's native TreeSHAP — `booster.predict(DMatrix(...),
pred_contribs=True)` computes the exact Shapley contribution of every feature per
prediction. This is the same algorithm the `shap` package's TreeExplainer provides,
but natively in the booster: no extra dependency, and fast enough to run per request.
The numbers below are always the actual SHAP output — never invented.

Translation layer: raw feature names never reach users; a deterministic display-name
map and sign→direction rule (positive SHAP → LATER, negative → EARLIER) turn them into
stable, human-readable factors. No LLM anywhere in this phase.

Safety: explanation is best-effort. Any failure (model unavailable, feature mismatch,
runtime error) yields `available=False` + a reason — the ETA itself is never affected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.ml.exceptions import ModelUnavailableError

logger = logging.getLogger(__name__)

# Raw feature -> user-facing display name (deterministic translation layer).
DISPLAY_NAMES: dict[str, str] = {
    "current_delay_minutes": "Current delay",
    "delay_trend_minutes": "Recent delay trend",
    "speed_kmph": "Current speed",
    "latitude": "Current GPS latitude",
    "longitude": "Current GPS longitude",
    "distance_to_next_station_km": "Distance to next station",
    "remaining_distance_km": "Remaining distance",
    "remaining_sections": "Remaining railway sections",
    "remaining_stations": "Remaining stations",
    "route_progress_percent": "Journey progress",
    "leg_scheduled_running_minutes": "Scheduled section running time",
    "leg_average_running_minutes": "Typical section running time",
    "leg_average_minus_scheduled_minutes": "Section historical delay",
    "leg_speed_limit_kmph": "Section speed limit",
    "scheduled_halt_minutes": "Scheduled station halt",
    "baseline_delay_minutes": "Baseline delay",
    "baseline_minutes_ahead": "Prediction horizon",
    "hour_of_day": "Time of day",
    "day_of_week": "Day of week",
    "month": "Month",
    "train_type_encoded": "Train type",
    "priority_encoded": "Train priority",
    "zone_encoded": "Railway zone",
    "station_encoded": "Station",
    "section_encoded": "Railway section",
}


class ExplanationUnavailableError(Exception):
    """Raised when an explanation cannot be produced; callers surface
    `available=false` with a reason instead of a fake explanation."""


@dataclass
class ExplanationFactor:
    feature: str
    display_name: str
    contribution_minutes: float
    direction: str  # LATER / EARLIER

    def as_dict(self) -> dict:
        return {
            "feature": self.feature,
            "display_name": self.display_name,
            "contribution_minutes": self.contribution_minutes,
            "direction": self.direction,
        }


def shap_contributions(loaded_model, vector: list[float]) -> list[tuple[str, float]]:
    """Exact TreeSHAP contributions for one prediction (feature, contribution_minutes),
    in the model's feature-column order. The trailing bias column is dropped.

    Raises ExplanationUnavailableError on any failure — never returns fabricated values.
    """
    import numpy as np
    import xgboost as xgb

    if len(vector) != len(loaded_model.feature_columns):
        raise ExplanationUnavailableError(
            f"feature mismatch: got {len(vector)} values, model expects {len(loaded_model.feature_columns)}"
        )
    try:
        matrix = xgb.DMatrix(np.asarray([vector], dtype=np.float32), feature_names=loaded_model.feature_columns)
        contribs = loaded_model.booster.predict(matrix, pred_contribs=True)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        raise ExplanationUnavailableError(f"SHAP computation failed: {exc}") from exc

    values = contribs[0]
    if len(values) != len(loaded_model.feature_columns) + 1:
        raise ExplanationUnavailableError("Unexpected SHAP output shape")
    return [
        (feature, float(value))
        for feature, value in zip(loaded_model.feature_columns, values[:-1])  # drop bias
    ]


def top_factors(contributions: list[tuple[str, float]], k: int | None = None) -> list[ExplanationFactor]:
    """Top-K factors by absolute contribution, translated for users. Positive SHAP
    pushes the residual later; negative pushes it earlier."""
    k = k if k is not None else get_settings().TOP_K_EXPLANATIONS
    ranked = sorted(contributions, key=lambda item: abs(item[1]), reverse=True)[:k]
    return [
        ExplanationFactor(
            feature=feature,
            display_name=DISPLAY_NAMES.get(feature, feature.replace("_", " ").title()),
            contribution_minutes=round(value, 2),
            direction="LATER" if value >= 0 else "EARLIER",
        )
        for feature, value in ranked
    ]


def explain_residual(loaded_model, vector: list[float]) -> list[ExplanationFactor]:
    """Convenience pipeline: SHAP contributions → translated top-K factors."""
    if loaded_model is None:
        raise ModelUnavailableError("No model provided")
    return top_factors(shap_contributions(loaded_model, vector))


def safe_explain(loaded_model, vector: list[float]) -> tuple[list[ExplanationFactor] | None, str | None]:
    """Best-effort explanation: (factors, None) or (None, reason). Never raises."""
    if loaded_model is None:
        return None, "ML_MODEL_UNAVAILABLE"
    try:
        return explain_residual(loaded_model, vector), None
    except ModelUnavailableError as exc:
        logger.info("Explanation unavailable (no model): %s", exc)
        return None, "ML_MODEL_UNAVAILABLE"
    except ExplanationUnavailableError as exc:
        logger.info("Explanation unavailable: %s", exc)
        return None, "EXPLANATION_UNAVAILABLE"
    except Exception as exc:  # noqa: BLE001 — explanation must never break the ETA
        logger.warning("Explanation unavailable: %s", exc, exc_info=True)
        return None, "EXPLANATION_UNAVAILABLE"
