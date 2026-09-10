from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "RAILCAST"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    FRONTEND_URL: str = "http://localhost:5173"
    DEMO_MODE: bool = True

    DATABASE_URL: str = "postgresql+psycopg://railcast:railcast@localhost:5433/railcast"
    REDIS_URL: str = "redis://localhost:6379/0"

    ML_MODEL_PATH: str = "./data/processed/models/xgboost_v1.json"
    MLFLOW_TRACKING_URI: str = "./mlruns"

    # --- Live data providers (Phase 4) ---
    PRIMARY_DATA_PROVIDER: str = "SIMULATOR"
    FALLBACK_DATA_PROVIDER: str = ""
    NTES_ENABLED: bool = False
    RAILRADAR_ENABLED: bool = False
    SIMULATOR_ENABLED: bool = True

    RAILRADAR_API_KEY: str = ""
    # Not in the original env var list, but required to avoid ever guessing/hardcoding
    # a RailRadar endpoint — see app/providers/railradar.py.
    RAILRADAR_BASE_URL: str = "https://api.railradar.in/v1"

    PROVIDER_TIMEOUT_SECONDS: float = 10.0
    PROVIDER_CACHE_TTL_SECONDS: int = 30
    # How long a provider is skipped (treated as unavailable without being called) after
    # a failure, so a known-down provider isn't hammered on every request. See module 12.
    PROVIDER_COOLDOWN_SECONDS: int = 60

    LIVE_INGESTION_INTERVAL_SECONDS: int = 30
    # Background polling is opt-in — the API must stay fully usable with this off.
    LIVE_INGESTION_ENABLED: bool = False

    # --- Baseline ETA engine (Phase 5) --------------------------------------------
    # These are RAILCAST model-configuration values chosen for sane, deterministic
    # behaviour — they do NOT represent official Indian Railways operating rules.
    BASELINE_MIN_SPEED_KMPH: float = 15.0
    BASELINE_MAX_SPEED_KMPH: float = 160.0
    BASELINE_FALLBACK_SPEED_KMPH: float = 55.0

    # Conservative delay-recovery model: a late train claws back at most
    # max(recovery_percent% of its current delay, capped per section) on each
    # remaining section. Replaced later by a learned recovery model.
    BASELINE_MAX_RECOVERY_PERCENT: float = 5.0
    BASELINE_MAX_RECOVERY_MINUTES_PER_SECTION: float = 2.0

    BASELINE_CACHE_TTL_SECONDS: int = 30
    # A TrainEvent older than this is treated as STALE: the baseline still computes
    # from it, but reports data_status=STALE instead of LIVE/SIMULATED.
    BASELINE_STALE_STATE_MINUTES: int = 30
    # GPS-only fallback: a train within this straight-line distance of a route station
    # is considered "at" that station by the approximate position resolver.
    BASELINE_GPS_STATION_PROXIMITY_KM: float = 2.0

    # --- ML residual ETA model (Phase 6) ---------------------------------------------
    # The ML layer ONLY learns a correction on top of the baseline ETA:
    #   FINAL ETA = BASELINE ETA + PREDICTED RESIDUAL
    # With no trained model available the API must still work — it falls back to the
    # baseline (prediction_mode=BASELINE_FALLBACK). Never an invented ML value.
    ML_MODEL_ENABLED: bool = True
    # Root directory of the lightweight model registry (models live in
    # {ML_MODEL_DIR}/eta_residual/{version}/). Existing ML_MODEL_PATH above stays
    # reserved for later single-file artefacts; the registry does not use it.
    ML_MODEL_DIR: str = "./models"
    # Which registry version is "active" for inference; empty means "latest trained".
    ML_MODEL_VERSION: str = ""
    # Safety clamp on the residual (RAILCAST model configuration, not railway policy):
    # a +240-minute prediction is clipped, never blindly applied.
    ML_RESIDUAL_MINUTES_MIN: float = -30.0
    ML_RESIDUAL_MINUTES_MAX: float = 60.0
    ML_CACHE_TTL_SECONDS: int = 30

    # Dataset generation defaults (scripts/build_ml_dataset.py).
    ML_DATASET_PATH: str = "./data/ml/eta_residual_dataset.parquet"
    ML_SYNTHETIC_DAYS: int = 90
    ML_SYNTHETIC_SEED: int = 42

    # Conservative XGBoost defaults; overridable per training run via CLI flags.
    ML_XGB_MAX_DEPTH: int = 5
    ML_XGB_LEARNING_RATE: float = 0.06
    ML_XGB_N_ESTIMATORS: int = 400
    ML_XGB_SUBSAMPLE: float = 0.85
    ML_XGB_COLSAMPLE_BYTREE: float = 0.85
    ML_XGB_MIN_CHILD_WEIGHT: float = 5.0
    ML_XGB_REG_LAMBDA: float = 1.0

    # Chronological split ratios (train/val/test over observation time).
    ML_SPLIT_TRAIN: float = 0.70
    ML_SPLIT_VALIDATION: float = 0.15

    # --- Uncertainty, confidence & explainability (Phase 7) ---------------------------
    # Nominal prediction-interval level (an "80% prediction interval", NOT a guarantee
    # of coverage — empirical coverage is reported separately by the evaluation).
    UNCERTAINTY_INTERVAL_LEVEL: float = 0.80
    # Conditional uncertainty: bucket horizon into minutes; groups smaller than
    # UNCERTAINTY_MIN_GROUP_SIZE fall back to the global residual quantiles.
    UNCERTAINTY_HORIZON_BUCKET_MINUTES: int = 60
    UNCERTAINTY_MIN_GROUP_SIZE: int = 50

    # Confidence score (0-100, NOT a probability of being on time). Transparent,
    # configurable weights for the additive factor model.
    CONFIDENCE_HIGH_THRESHOLD: int = 80
    CONFIDENCE_MEDIUM_THRESHOLD: int = 50
    CONFIDENCE_MAX_DATA_AGE_SECONDS: int = 120
    CONFIDENCE_LONG_HORIZON_MINUTES: float = 120.0

    # Explanations: number of top factors returned (sorted by |SHAP|).
    TOP_K_EXPLANATIONS: int = 5
    # Redis TTL for cached explanation payloads.
    EXPLANATION_CACHE_TTL_SECONDS: int = 60

    # --- Network intelligence & delay-propagation (Phase 8) ---------------------------
    # RAILCAST analytical model configuration — NOT official Indian Railways risk
    # classifications, signalling logic, or operational commands. See app/network/.
    NETWORK_ANALYSIS_ENABLED: bool = True
    # Only future movements within this window are analyzed — no indefinite propagation.
    NETWORK_ANALYSIS_HORIZON_MINUTES: int = 180
    NETWORK_MAX_PROPAGATION_DEPTH: int = 3
    NETWORK_MIN_PROPAGATED_DELAY_MINUTES: float = 2.0
    # Multiplicative decay applied per propagation hop (depth 0 -> 1.0, depth 1 -> this
    # value, depth 2 -> this value squared, ...).
    NETWORK_PROPAGATION_DECAY: float = 0.60
    # Bounds any single analysis (single-train or network-wide) to at most this many
    # trains — a deliberately bounded graph walk, never a full-table scan.
    NETWORK_MAX_TRAINS_PER_ANALYSIS: int = 500
    # Impact-score (0-100) severity thresholds. LOW is anything below MEDIUM.
    NETWORK_MEDIUM_IMPACT_THRESHOLD: int = 25
    NETWORK_HIGH_IMPACT_THRESHOLD: int = 50
    NETWORK_CRITICAL_IMPACT_THRESHOLD: int = 75
    # A predictive Alert is only created when a train's network_impact_score reaches this.
    NETWORK_ALERT_THRESHOLD: int = 60
    # Two trains scheduled within this many minutes of each other on a shared section
    # (but not actually overlapping) are flagged INSUFFICIENT_SEPARATION.
    NETWORK_MIN_SAFE_SEPARATION_MINUTES: float = 15.0
    # Redis cache TTL for the bounded railway graph (module 32).
    NETWORK_GRAPH_CACHE_TTL_SECONDS: int = 60

    # --- Real-Time Streaming & Continuous Prediction Pipeline (Phase 9) ---------------
    STREAMING_ENABLED: bool = True
    REDIS_STREAM_TRAIN_EVENTS: str = "railcast:train-events"
    REDIS_STREAM_PREDICTIONS: str = "railcast:prediction-updates"
    REDIS_CONSUMER_GROUP: str = "railcast-prediction-workers"
    REDIS_CONSUMER_NAME: str = "worker-1"
    STREAM_MAXLEN: int = 10000
    PREDICTION_DEBOUNCE_SECONDS: float = 5.0
    NETWORK_RECALC_DELAY_CHANGE_MINUTES: float = 2.0
    NETWORK_RECALC_POSITION_CHANGE_KM: float = 5.0
    NETWORK_RECALC_MIN_INTERVAL_SECONDS: float = 30.0
    WEBSOCKET_MAX_QUEUE_SIZE: int = 100
    WEBSOCKET_PING_INTERVAL_SECONDS: float = 20.0

    # --- Productionization, Monitoring, Retraining & MLOps (Phase 10) -------------------
    ADMIN_API_KEY: str = ""
    ADMIN_AUTH_ENABLED: bool = True
    DRIFT_CHECK_ENABLED: bool = True
    DRIFT_WINDOW_DAYS: int = 7
    MODEL_DRIFT_THRESHOLD: float = 0.20
    DATA_DRIFT_THRESHOLD: float = 0.20
    MODEL_MIN_IMPROVEMENT_PERCENT: float = 2.0
    MIN_EVALUATION_SAMPLES: int = 30
    FEATURE_SCHEMA_VERSION: str = "features-v1"
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120
    RAILCAST_MODE: str = "DEMO"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if self.FRONTEND_URL and self.FRONTEND_URL.strip() and self.FRONTEND_URL.strip() not in origins:
            origins.append(self.FRONTEND_URL.strip())
        return origins

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
