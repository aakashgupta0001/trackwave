"""API response schemas for the Baseline ETA engine (Phase 5).

Contract notes:
- `scheduled_arrival` is always the untouched static-timetable value — the baseline
  engine never overwrites or "corrects" it. Keeping both side by side is what later
  lets Phase 6+ learn the residual (FINAL ETA = BASELINE + ML RESIDUAL).
- `prediction_mode` is BASELINE for the normal section-aware path and BASELINE_FALLBACK
  when a station's ETA had to be reconstructed from travel-time estimates instead of
  the timetable.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import PredictionMode
from app.providers.models import DataStatus


class UncertaintyInterval(BaseModel):
    """A nominal-level prediction interval derived from held-out residual quantiles —
    NOT a guarantee of coverage (empirical coverage is measured and reported
    separately). lower/upper need not be symmetric around the final ETA."""

    lower_eta: datetime
    upper_eta: datetime
    interval_level: float = Field(description="Nominal level, e.g. 0.80")
    interval_width_minutes: float
    source: str | None = Field(default=None, description="GLOBAL_QUANTILES / HORIZON_BUCKET_QUANTILES")


class ConfidenceFactorOut(BaseModel):
    factor: str
    impact: str  # POSITIVE / NEGATIVE / NEUTRAL


class ConfidenceOut(BaseModel):
    """0-100 confidence in the QUALITY of this prediction — not a probability of
    arriving on time, and the level is not a statistical likelihood."""

    score: int = Field(ge=0, le=100)
    level: str  # HIGH / MEDIUM / LOW
    factors: list[ConfidenceFactorOut] = Field(default_factory=list)


class ExplanationFactorOut(BaseModel):
    feature: str
    display_name: str
    contribution_minutes: float
    direction: str  # LATER / EARLIER


class ExplanationOut(BaseModel):
    available: bool
    reason: str | None = None
    top_factors: list[ExplanationFactorOut] = Field(default_factory=list)


class CurrentPosition(BaseModel):
    kind: str = Field(description="AT_STATION | DEPARTED_STATION | IN_SECTION | GPS_ONLY | NO_POSITION")
    position_source: str = Field(description="Where the position knowledge came from (explainability)")
    station_code: str | None = None
    section_code: str | None = None
    last_known_station_code: str | None = None
    next_station_code: str | None = None


class EtaCalculationDetails(BaseModel):
    """Per-station explainability metadata (future input to RailExplain)."""

    position_source: str
    distance_source: str
    speed_source: str | None = None
    running_time_source: str | None = None
    expected_speed_kmph: float | None = None
    section_distance_km: float | None = None
    delay_input_minutes: float | None = None
    recovery_applied_minutes: float | None = None
    estimated_halt_minutes: float | None = None


from typing import Any


class EtaStation(BaseModel):
    station_code: str
    station_name: str
    sequence_number: int
    scheduled_arrival: datetime | None = None
    scheduled_eta: datetime | None = None
    baseline_eta: datetime | None = None
    delay_minutes: float = Field(description="baseline_eta − scheduled_arrival, in minutes (>= 0)")
    remaining_distance_km: float
    prediction_mode: PredictionMode
    calculation_details: EtaCalculationDetails | None = None
    # --- Phase 6: ML residual fusion (null/absent when the baseline engine runs alone) ---
    predicted_residual_minutes: float | None = Field(default=None, description="Clamped residual applied to the baseline")
    ml_residual_minutes: float | None = None
    predicted_residual_raw: float | None = Field(default=None, description="Raw model output before the safety clamp")
    residual_clipped: bool = Field(default=False, description="True when the safety clamp reduced the raw residual")
    final_eta: datetime | None = Field(default=None, description="baseline_eta + predicted residual")
    final_delay_minutes: float | None = Field(default=None, description="final_eta − scheduled_arrival, in minutes")
    lower_bound: datetime | None = None
    upper_bound: datetime | None = None
    confidence_score: int | None = None
    confidence_level: str | None = None
    # --- Phase 7: uncertainty, confidence, explanation ---------------------------------
    uncertainty: UncertaintyInterval | None = None
    confidence: ConfidenceOut | None = None
    explanation: ExplanationOut | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.scheduled_eta is None:
            self.scheduled_eta = self.scheduled_arrival
        if self.ml_residual_minutes is None:
            self.ml_residual_minutes = self.predicted_residual_minutes
        if self.uncertainty is not None:
            if self.lower_bound is None:
                self.lower_bound = self.uncertainty.lower_eta
            if self.upper_bound is None:
                self.upper_bound = self.uncertainty.upper_eta
        if self.confidence is not None:
            if self.confidence_score is None:
                self.confidence_score = self.confidence.score
            if self.confidence_level is None:
                self.confidence_level = self.confidence.level


class BaselineEtaResponse(BaseModel):
    train_number: str
    train_name: str
    generated_at: datetime
    prediction_timestamp: datetime | None = None
    journey_date: date
    prediction_mode: PredictionMode = PredictionMode.BASELINE
    model_version: str | None = Field(default=None, description="ML model version when a residual model was applied")
    data_source: str | None = None
    data_status: DataStatus
    provider_status: str | None = None
    status: str | None = None
    retrieved_at: datetime | None = None
    data_age_seconds: float | None = None
    current_position: CurrentPosition
    remaining_distance_km: float = Field(description="Railway distance from the train's current position to its destination")
    stations: list[EtaStation]
    calculation_details: dict = Field(default_factory=dict, description="Engine-level explainability metadata")

    def model_post_init(self, __context: Any) -> None:
        if self.prediction_timestamp is None:
            self.prediction_timestamp = self.generated_at
        if self.provider_status is None:
            self.provider_status = self.data_status.value if hasattr(self.data_status, "value") else str(self.data_status)
        if self.status is None:
            self.status = self.provider_status


class SingleStationEtaResponse(BaseModel):
    train_number: str
    station_code: str
    station_name: str
    scheduled_arrival: datetime | None = None
    scheduled_eta: datetime | None = None
    baseline_eta: datetime | None = None
    delay_minutes: float = Field(description="baseline_eta − scheduled_arrival, in minutes (>= 0)")
    predicted_residual_minutes: float | None = None
    ml_residual_minutes: float | None = None
    predicted_residual_raw: float | None = None
    residual_clipped: bool = False
    final_eta: datetime | None = None
    final_delay_minutes: float | None = None
    remaining_distance_km: float
    prediction_mode: PredictionMode
    model_version: str | None = None
    data_source: str | None = None
    data_status: DataStatus
    provider_status: str | None = None
    status: str | None = None
    retrieved_at: datetime | None = None
    data_age_seconds: float | None = None
    prediction_timestamp: datetime | None = None
    lower_bound: datetime | None = None
    upper_bound: datetime | None = None
    confidence_score: int | None = None
    confidence_level: str | None = None
    calculation_details: EtaCalculationDetails | None = None
    uncertainty: UncertaintyInterval | None = None
    confidence: ConfidenceOut | None = None
    explanation: ExplanationOut | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.scheduled_eta is None:
            self.scheduled_eta = self.scheduled_arrival
        if self.ml_residual_minutes is None:
            self.ml_residual_minutes = self.predicted_residual_minutes
        if self.uncertainty is not None:
            if self.lower_bound is None:
                self.lower_bound = self.uncertainty.lower_eta
            if self.upper_bound is None:
                self.upper_bound = self.uncertainty.upper_eta
        if self.confidence is not None:
            if self.confidence_score is None:
                self.confidence_score = self.confidence.score
            if self.confidence_level is None:
                self.confidence_level = self.confidence.level
        if self.provider_status is None:
            self.provider_status = self.data_status.value if hasattr(self.data_status, "value") else str(self.data_status)
        if self.status is None:
            self.status = self.provider_status


class BaselineFactorOut(BaseModel):
    factor: str
    display_name: str
    effect: str
    value: float | None = None


class FullExplanationResponse(BaseModel):
    """Response of GET /eta/{train}/{station}/explanation: baseline factors are always
    deterministic; ML factors come from exact TreeSHAP on the active model and are
    omitted with an explicit reason when unavailable — never faked."""

    train_number: str
    station_code: str
    prediction_mode: PredictionMode
    model_version: str | None = None
    prediction_timestamp: datetime | None = None
    final_eta: datetime | None = None
    predicted_residual_minutes: float | None = None
    available: bool = Field(description="False when no ML explanation could be produced")
    reason: str | None = None
    baseline_factors: list[BaselineFactorOut] = Field(default_factory=list)
    ml_factors: list[ExplanationFactorOut] = Field(default_factory=list)
