from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TrainPriority, TrainType


class TrainBase(BaseModel):
    train_number: str = Field(max_length=10)
    train_name: str = Field(max_length=100)
    train_type: TrainType
    source_station_id: int
    destination_station_id: int
    zone: str = Field(max_length=10)
    priority: TrainPriority = TrainPriority.NORMAL
    active: bool = True


class TrainCreate(TrainBase):
    pass


class TrainRead(TrainBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# API-facing (Phase 3) response schemas. Unlike TrainRead above, these are
# frontend-shaped: station codes/names instead of internal station_id foreign
# keys, and no SQLAlchemy internals. Built explicitly in the API layer via the
# `from_train` helpers rather than `model_validate(orm_obj)`, since field names
# and shape diverge from the ORM model.
# ---------------------------------------------------------------------------


class TrainListItem(BaseModel):
    train_number: str
    train_name: str
    train_type: TrainType
    source_station_code: str
    source_station_name: str
    destination_station_code: str
    destination_station_name: str
    zone: str
    priority: TrainPriority
    active: bool

    @classmethod
    def from_train(cls, train) -> "TrainListItem":
        return cls(
            train_number=train.train_number,
            train_name=train.train_name,
            train_type=train.train_type,
            source_station_code=train.source_station.station_code,
            source_station_name=train.source_station.station_name,
            destination_station_code=train.destination_station.station_code,
            destination_station_name=train.destination_station.station_name,
            zone=train.zone,
            priority=train.priority,
            active=train.active,
        )


class TrainRouteSummary(BaseModel):
    total_stations: int
    total_distance_km: float | None
    origin_departure_time: time | None
    destination_arrival_time: time | None
    destination_arrival_day_offset: int | None


class TrainDetail(BaseModel):
    train_number: str
    train_name: str
    train_type: TrainType
    source_station_code: str
    source_station_name: str
    destination_station_code: str
    destination_station_name: str
    zone: str
    priority: TrainPriority
    active: bool
    created_at: datetime
    updated_at: datetime
    route_summary: TrainRouteSummary | None

    @classmethod
    def from_train(cls, train) -> "TrainDetail":
        routes = sorted(train.routes, key=lambda r: r.sequence_number)
        summary = None
        if routes:
            summary = TrainRouteSummary(
                total_stations=len(routes),
                total_distance_km=float(routes[-1].distance_from_origin_km),
                origin_departure_time=routes[0].scheduled_departure,
                destination_arrival_time=routes[-1].scheduled_arrival,
                destination_arrival_day_offset=routes[-1].day_offset,
            )
        return cls(
            train_number=train.train_number,
            train_name=train.train_name,
            train_type=train.train_type,
            source_station_code=train.source_station.station_code,
            source_station_name=train.source_station.station_name,
            destination_station_code=train.destination_station.station_code,
            destination_station_name=train.destination_station.station_name,
            zone=train.zone,
            priority=train.priority,
            active=train.active,
            created_at=train.created_at,
            updated_at=train.updated_at,
            route_summary=summary,
        )
