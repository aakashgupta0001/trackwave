from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AlertSeverity, AlertType


class AlertBase(BaseModel):
    alert_type: AlertType
    severity: AlertSeverity
    train_id: int | None = None
    section_id: int | None = None
    station_id: int | None = None
    title: str = Field(max_length=200)
    description: str | None = None
    resolved_at: datetime | None = None
    # Exposed as "metadata" over the API; backed by the ORM's `alert_metadata`
    # attribute (see app.models.alert.Alert for why).
    metadata: dict | None = Field(default=None, validation_alias="alert_metadata", serialization_alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class AlertCreate(AlertBase):
    pass


class AlertRead(AlertBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    created_at: datetime
