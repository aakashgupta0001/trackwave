from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PredictionMode


class PredictionBase(BaseModel):
    train_id: int
    station_id: int
    prediction_timestamp: datetime
    scheduled_eta: datetime | None = None
    baseline_eta: datetime | None = None
    ml_correction_minutes: float | None = None
    final_eta: datetime | None = None
    lower_bound: datetime | None = None
    upper_bound: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = None
    prediction_mode: PredictionMode | None = None
    actual_arrival: datetime | None = None
    error_minutes: float | None = None


class PredictionCreate(PredictionBase):
    pass


class PredictionRead(PredictionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
