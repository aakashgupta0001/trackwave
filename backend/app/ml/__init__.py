"""RAILCAST ML residual ETA model (Phase 6).

Architecture (mandatory residual learning — the ML layer NEVER produces an absolute ETA):

    CURRENT TRAIN STATE -> BASELINE ETA -> FEATURE ENGINEERING -> ML RESIDUAL PREDICTOR
        -> PREDICTED RESIDUAL -> FINAL ETA = BASELINE ETA + RESIDUAL

Modules:
    features    — railway-aware feature building (single source of truth for training
                  AND inference; only uses information available at prediction time)
    target      — residual target definition
    dataset     — dataset building (real history when available, otherwise an
                  explicitly-labelled SYNTHETIC generator for development)
    model       — XGBoost model wrapper (save/load/feature importance)
    predictor   — lazy-loaded inference entry point (never trains at request time)
    registry    — lightweight filesystem model registry (versioning + metadata)
    training    — reproducible training pipeline (chronological split, evaluation)
    evaluation  — metrics + mandatory baseline-vs-ML comparison
    fallback    — guaranteed degradation to the baseline ETA
"""

from app.ml.exceptions import ModelUnavailableError

__all__ = ["ModelUnavailableError"]
