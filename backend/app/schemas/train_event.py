from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EventSource, EventType


class TrainEventBase(BaseModel):
    train_id: int
    timestamp: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    speed_kmph: float | None = Field(default=None, ge=0)
    station_id: int | None = None
    section_id: int | None = None
    delay_minutes: int = 0
    event_type: EventType
    event_source: EventSource
    # Exposed as "metadata" over the API; backed by the ORM's `event_metadata`
    # attribute (see app.models.train_event.TrainEvent for why).
    metadata: dict | None = Field(default=None, validation_alias="event_metadata", serialization_alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class TrainEventCreate(TrainEventBase):
    pass


class TrainEventRead(TrainEventBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# API-facing (Phase 3) response schemas — see app/schemas/train.py for why
# these are separate from TrainEventRead above (station/section codes, not
# internal IDs).
# ---------------------------------------------------------------------------


class TrainEventResponse(BaseModel):
    id: int
    timestamp: datetime
    event_type: EventType
    event_source: EventSource
    station_code: str | None
    section_code: str | None
    delay_minutes: int
    speed_kmph: float | None
    latitude: float | None
    longitude: float | None
    metadata: dict | None

    @classmethod
    def from_event(cls, event) -> "TrainEventResponse":
        return cls(
            id=event.id,
            timestamp=event.timestamp,
            event_type=event.event_type,
            event_source=event.event_source,
            station_code=event.station.station_code if event.station is not None else None,
            section_code=event.section.section_code if event.section is not None else None,
            delay_minutes=event.delay_minutes,
            speed_kmph=float(event.speed_kmph) if event.speed_kmph is not None else None,
            latitude=float(event.latitude) if event.latitude is not None else None,
            longitude=float(event.longitude) if event.longitude is not None else None,
            metadata=event.event_metadata,
        )


class TrainStateResponse(BaseModel):
    train_number: str
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    speed_kmph: float | None
    station_code: str | None
    section_code: str | None
    delay_minutes: int
    event_type: EventType
    event_source: EventSource
    metadata: dict | None
    data_freshness_seconds: float

    @classmethod
    def from_event(cls, train_number: str, event, *, now: datetime) -> "TrainStateResponse":
        return cls(
            train_number=train_number,
            timestamp=event.timestamp,
            latitude=float(event.latitude) if event.latitude is not None else None,
            longitude=float(event.longitude) if event.longitude is not None else None,
            speed_kmph=float(event.speed_kmph) if event.speed_kmph is not None else None,
            station_code=event.station.station_code if event.station is not None else None,
            section_code=event.section.section_code if event.section is not None else None,
            delay_minutes=event.delay_minutes,
            event_type=event.event_type,
            event_source=event.event_source,
            metadata=event.event_metadata,
            data_freshness_seconds=max(0.0, (now - event.timestamp).total_seconds()),
        )
