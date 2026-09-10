from datetime import datetime, time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import StationType


class StationBase(BaseModel):
    station_code: str = Field(max_length=10)
    station_name: str = Field(max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    zone: str = Field(max_length=10)
    division: str | None = Field(default=None, max_length=50)
    state: str | None = Field(default=None, max_length=50)
    station_type: StationType


class StationCreate(StationBase):
    pass


class StationRead(StationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# API-facing (Phase 3) response schemas — see app/schemas/train.py for why
# these are separate from StationRead above.
# ---------------------------------------------------------------------------


class StationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_code: str
    station_name: str
    zone: str
    state: str | None
    station_type: StationType


class StationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    station_code: str
    station_name: str
    latitude: float
    longitude: float
    zone: str
    division: str | None
    state: str | None
    station_type: StationType


class BoardStatus(str, Enum):
    """Derived purely from the latest already-known TrainEvent.delay_minutes — not a
    forecast. See module docstring in app/api/routes/stations.py for why this stays
    a simple label rather than anything ETA-shaped.
    """

    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    NO_RECENT_DATA = "NO_RECENT_DATA"


class StationBoardItem(BaseModel):
    train_number: str
    train_name: str
    source_station_code: str
    destination_station_code: str
    scheduled_arrival: time | None
    scheduled_departure: time | None
    latest_known_delay_minutes: int | None
    latest_event_timestamp: datetime | None
    status: BoardStatus

    @classmethod
    def build(cls, route, latest_event) -> "StationBoardItem":
        """`route` is this train's TrainRoute entry at the station being boarded;
        `latest_event` is that train's most recent known TrainEvent overall (may be
        None, or may concern a different station/section — it's the train's latest
        known state, not necessarily an event at this station).
        """
        if latest_event is None:
            status = BoardStatus.NO_RECENT_DATA
        elif latest_event.delay_minutes > 0:
            status = BoardStatus.DELAYED
        else:
            status = BoardStatus.ON_TIME

        return cls(
            train_number=route.train.train_number,
            train_name=route.train.train_name,
            source_station_code=route.train.source_station.station_code,
            destination_station_code=route.train.destination_station.station_code,
            scheduled_arrival=route.scheduled_arrival,
            scheduled_departure=route.scheduled_departure,
            latest_known_delay_minutes=latest_event.delay_minutes if latest_event is not None else None,
            latest_event_timestamp=latest_event.timestamp if latest_event is not None else None,
            status=status,
        )


class StationBoardResponse(BaseModel):
    station_code: str
    station_name: str
    generated_at: datetime
    board: list[StationBoardItem]


class StationTrainItem(BaseModel):
    train_number: str
    train_name: str
    source_station_code: str
    destination_station_code: str
    sequence_number: int
    scheduled_arrival: time | None
    scheduled_departure: time | None
    halt_minutes: int

    @classmethod
    def from_route(cls, route) -> "StationTrainItem":
        return cls(
            train_number=route.train.train_number,
            train_name=route.train.train_name,
            source_station_code=route.train.source_station.station_code,
            destination_station_code=route.train.destination_station.station_code,
            sequence_number=route.sequence_number,
            scheduled_arrival=route.scheduled_arrival,
            scheduled_departure=route.scheduled_departure,
            halt_minutes=route.halt_minutes,
        )
