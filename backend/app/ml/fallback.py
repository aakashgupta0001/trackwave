"""Fallback strategy (Phase 6): when anything in the ML layer is unavailable or fails,
FINAL ETA = BASELINE ETA with prediction_mode=BASELINE_FALLBACK. An invented ML value
is never returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from app.ml.exceptions import ModelPredictionError, ModelUnavailableError

logger = logging.getLogger(__name__)

# Reasons surfaced for explainability / monitoring.
REASON_DISABLED = "ML_MODEL_DISABLED"
REASON_NO_MODEL = "NO_TRAINED_MODEL"
REASON_FEATURES = "FEATURES_UNAVAILABLE"
REASON_PREDICTION_ERROR = "PREDICTION_ERROR"


@dataclass
class FallbackOutcome:
    residual_minutes: float | None  # None → use baseline alone
    model_version: str | None
    reason: str | None  # set when fallback happened

    @property
    def used_ml(self) -> bool:
        return self.residual_minutes is not None


def safe_predict(predict: Callable[[], float], model_version: str | None) -> FallbackOutcome:
    """Run one ML prediction, mapping every failure mode to a baseline fallback with an
    explicit reason. Never raises; never invents a value."""
    try:
        residual = predict()
    except ModelUnavailableError as exc:
        reason = REASON_DISABLED if "disabled" in str(exc).lower() else REASON_NO_MODEL
        logger.info("ML fallback (%s): %s", reason, exc)
        return FallbackOutcome(None, None, reason)
    except ModelPredictionError as exc:
        logger.warning("ML fallback (%s): %s", REASON_PREDICTION_ERROR, exc)
        return FallbackOutcome(None, None, REASON_PREDICTION_ERROR)
    except Exception as exc:  # noqa: BLE001 — the ML layer must never take ETA down
        logger.warning("ML fallback (%s): %s", REASON_PREDICTION_ERROR, exc, exc_info=True)
        return FallbackOutcome(None, None, REASON_PREDICTION_ERROR)
    return FallbackOutcome(residual, model_version, None)
