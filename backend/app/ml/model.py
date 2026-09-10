"""XGBoost model wrapper (Phase 6 — regression on residual minutes).

Training happens ONLY via app.ml.training (offline); inference loads a booster from
the registry. No deep learning — XGBoost is the Phase 6 production baseline model.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml.features import FEATURE_COLUMNS


def model_params(seed: int = 42) -> dict:
    """Conservatively-regularized XGBoost parameters; every key hyperparameter comes
    from configuration so tuning never requires code changes. Uses the Booster API
    (xgb.train) directly — the sklearn wrapper would pull in scikit-learn, which Phase 6
    does not otherwise need."""
    s = get_settings()
    return {
        "max_depth": s.ML_XGB_MAX_DEPTH,
        "learning_rate": s.ML_XGB_LEARNING_RATE,
        "subsample": s.ML_XGB_SUBSAMPLE,
        "colsample_bytree": s.ML_XGB_COLSAMPLE_BYTREE,
        "min_child_weight": s.ML_XGB_MIN_CHILD_WEIGHT,
        "reg_lambda": s.ML_XGB_REG_LAMBDA,
        "seed": seed,
        "n_jobs": 1,
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "verbosity": 0,
    }


def num_boost_round() -> int:
    return get_settings().ML_XGB_N_ESTIMATORS


def feature_importance(booster) -> list[dict]:
    """Gain-based importance ranking (prepares future RailExplain; SHAP is NOT part of
    this phase). Returns a list sorted most-important-first."""
    scores = booster.get_score(importance_type="gain")
    known = [c for c in FEATURE_COLUMNS if c in scores]
    # Features never used by any split are absent from the score map — report them last.
    missing = [c for c in FEATURE_COLUMNS if c not in scores]
    ranked = sorted(known, key=lambda c: scores[c], reverse=True)
    return [
        {"feature": c, "gain": float(scores[c]) if c in scores else 0.0}
        for c in ranked + missing
    ]
