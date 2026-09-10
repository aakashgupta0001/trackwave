"""Pydantic response models and enums for Phase 10 monitoring and MLOps."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OverallSystemStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ComponentStatus(str, Enum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNAVAILABLE = "UNAVAILABLE"


class SystemHealthResponse(BaseModel):
    status: OverallSystemStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = Field(default="0.1.0")
    components: dict[str, str] = Field(
        description="Key component states: database, redis, streaming, model, provider, network"
    )
    details: dict[str, Any] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    ready: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checks: dict[str, bool]


class LivenessResponse(BaseModel):
    alive: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DataQualityRating(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DataQualityDimension(BaseModel):
    score: float = Field(ge=0.0, le=25.0)
    status: str
    description: str


class DataQualityResponse(BaseModel):
    score: float = Field(ge=0.0, le=100.0, description="Internal RAILCAST data-quality score")
    rating: DataQualityRating
    completeness: DataQualityDimension
    freshness: DataQualityDimension
    validity: DataQualityDimension
    consistency: DataQualityDimension
    metrics: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeatureDriftResult(BaseModel):
    feature_name: str
    psi_score: float
    ks_statistic: float
    ks_p_value: float
    drift_detected: bool


class ModelDriftResult(BaseModel):
    active_model_version: str
    reference_mae: float
    recent_mae: float
    degradation_percent: float
    sample_count: int
    drift_detected: bool


class DriftAnalysisResponse(BaseModel):
    data_drift_detected: bool
    model_drift_detected: bool
    window_days: int
    data_drift_threshold: float
    model_drift_threshold: float
    feature_drifts: list[FeatureDriftResult]
    model_drift: ModelDriftResult | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HorizonMetric(BaseModel):
    horizon_bucket: str
    sample_count: int
    scheduled_mae: float | None = None
    baseline_mae: float | None = None
    ml_mae: float | None = None
    improvement_percent: float | None = None


class GroupMetric(BaseModel):
    group_type: str
    group_value: str
    sample_count: int
    baseline_mae: float | None = None
    ml_mae: float | None = None
    improvement_percent: float | None = None


class ModelEvaluationResponse(BaseModel):
    model_version: str
    total_samples: int
    scheduled_mae: float | None = None
    baseline_mae: float | None = None
    ml_mae: float | None = None
    ml_rmse: float | None = None
    median_absolute_error: float | None = None
    p90_absolute_error: float | None = None
    mean_error_bias: float | None = None
    improvement_vs_baseline_percent: float | None = None
    by_horizon: list[HorizonMetric] = Field(default_factory=list)
    by_train_type: list[GroupMetric] = Field(default_factory=list)
    by_data_source: list[GroupMetric] = Field(default_factory=list)
    uncertainty_coverage_percent: float | None = None
    uncertainty_target_percent: float = 80.0
    uncertainty_avg_width_minutes: float | None = None
    confidence_calibration: dict[str, Any] = Field(default_factory=dict)
    evaluation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderMetricsResponse(BaseModel):
    providers: dict[str, dict[str, Any]]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StreamingMetricsResponse(BaseModel):
    events_ingested_total: int
    events_debounced_total: int
    predictions_calculated_total: int
    network_recalcs_total: int
    events_out_of_order_total: int
    events_duplicate_total: int
    stream_lag: int
    latency_percentiles_ms: dict[str, float]
    worker_status: str
    last_event_time: str | None = None
    last_prediction_time: str | None = None


class ModelStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    STAGED = "STAGED"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class ModelMetadataResponse(BaseModel):
    model_version: str
    status: ModelStatus
    training_timestamp: str | None = None
    dataset_version: str | None = None
    feature_schema_version: str | None = None
    test_mae: float | None = None
    baseline_mae: float | None = None
    improvement_percent: float | None = None
    uncertainty_level: float | None = None
    artifact_path: str


class ModelCatalogResponse(BaseModel):
    active_model: str | None
    staged_model: str | None
    models: list[ModelMetadataResponse]


class AuditLogEntry(BaseModel):
    id: str
    action: str
    actor: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
