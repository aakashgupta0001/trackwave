from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field


class TrainRouteBase(BaseModel):
    train_id: int
    station_id: int
    section_id: int | None = None
    sequence_number: int = Field(ge=1)
    scheduled_arrival: time | None = None
    scheduled_departure: time | None = None
    day_offset: int = Field(default=0, ge=0)
    halt_minutes: int = Field(default=0, ge=0)
    distance_from_origin_km: float = Field(ge=0)


class TrainRouteCreate(TrainRouteBase):
    pass


class TrainRouteRead(TrainRouteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# API-facing (Phase 3) response schemas — see app/schemas/train.py for why
# these are separate from TrainRouteRead above (station codes, not IDs; API
# field names arrival_time/departure_time rather than the DB's scheduled_*).
# ---------------------------------------------------------------------------


class TrainRouteItem(BaseModel):
    sequence_number: int
    station_code: str
    station_name: str
    arrival_time: time | None
    departure_time: time | None
    day_offset: int
    halt_minutes: int
    distance_from_source_km: float
    section_code: str | None

    @classmethod
    def from_route(cls, route) -> "TrainRouteItem":
        return cls(
            sequence_number=route.sequence_number,
            station_code=route.station.station_code,
            station_name=route.station.station_name,
            arrival_time=route.scheduled_arrival,
            departure_time=route.scheduled_departure,
            day_offset=route.day_offset,
            halt_minutes=route.halt_minutes,
            distance_from_source_km=float(route.distance_from_origin_km),
            section_code=route.section.section_code if route.section is not None else None,
        )


class TrainRouteResponse(BaseModel):
    train_number: str
    train_name: str
    source: str
    destination: str
    route: list[TrainRouteItem]


class TrainUpcomingResponse(BaseModel):
    train_number: str
    train_name: str
    has_known_state: bool
    as_of: datetime | None
    current_station_code: str | None
    current_section_code: str | None
    current_delay_minutes: int | None
    upcoming: list[TrainRouteItem]
