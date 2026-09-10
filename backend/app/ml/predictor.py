"""ML residual predictor (Phase 6 inference entry point).

Loads the active model from the registry lazily and caches it in memory. A request
NEVER trains a model: if nothing usable is loaded, `ModelUnavailableError` is raised
and the fusion layer falls back to the baseline ETA.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from app.core.config import get_settings
from app.ml.exceptions import ModelPredictionError, ModelUnavailableError
from app.ml.features import FeatureContext, build_feature_row, encode_row, row_to_vector
from app.ml.registry import LoadedModel, ModelRegistry

logger = logging.getLogger(__name__)


@dataclass
class ResidualPrediction:
    raw_residual_minutes: float
    model_version: str
    prediction_timestamp: datetime
    feature_timestamp: datetime


class ResidualPredictor:
    """Holds the active model; safe to reuse across requests."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._registry = registry or ModelRegistry(get_settings().ML_MODEL_DIR)
        self._loaded: LoadedModel | None = None
        self._loaded_at: datetime | None = None

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    @property
    def model_version(self) -> str | None:
        try:
            return self._ensure_loaded().version
        except Exception:
            return None

    def is_available(self) -> bool:
        try:
            self._ensure_loaded()
            return True
        except ModelUnavailableError:
            return False

    def _ensure_loaded(self) -> LoadedModel:
        settings = get_settings()
        if not settings.ML_MODEL_ENABLED:
            raise ModelUnavailableError("ML model is disabled by configuration (ML_MODEL_ENABLED=false)")
        # Re-check the registry at most every 60s so a newly trained model is picked
        # up without a restart, without stat()-ing the filesystem on every request.
        now = datetime.now(timezone.utc)
        if self._loaded is None or (self._loaded_at and (now - self._loaded_at).total_seconds() > 60):
            self._loaded = self._registry.load()
            self._loaded_at = now
            logger.info("Loaded ML model version=%s", self._loaded.version)
        return self._loaded

    def reload(self) -> LoadedModel | None:
        """Explicitly invalidate in-memory cache and reload the active model."""
        self._loaded = None
        self._loaded_at = None
        try:
            return self._ensure_loaded()
        except ModelUnavailableError:
            return None

    def predict(self, ctx: FeatureContext) -> ResidualPrediction:
        """Build features for one context and predict the residual (minutes)."""
        loaded = self._ensure_loaded()
        try:
            raw_row = build_feature_row(ctx)
            encoded = encode_row(raw_row, loaded.encoder)
            if all(math.isnan(v) for v in encoded.values()):
                raise ModelPredictionError("All features are missing — refusing to predict")
            vector = row_to_vector(encoded)
            import xgboost as xgb

            matrix = xgb.DMatrix(np.asarray([vector], dtype=np.float32), feature_names=loaded.feature_columns)
            prediction = float(loaded.booster.predict(matrix)[0])
        except (ModelPredictionError, ModelUnavailableError):
            raise
        except Exception as exc:
            raise ModelPredictionError(f"Residual prediction failed: {exc}") from exc

        now = datetime.now(timezone.utc)
        return ResidualPrediction(
            raw_residual_minutes=prediction,
            model_version=loaded.version,
            prediction_timestamp=now,
            feature_timestamp=ctx.prediction_time,
        )


ml_predictor = ResidualPredictor()
