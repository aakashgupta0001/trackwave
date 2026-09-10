from datetime import datetime, time, timezone
from typing import Any

from pydantic import BaseModel

from app.models.enums import EventType
from app.providers.manager import LiveResult
from app.providers.models import DataStatus, ProviderName, StationBoard, TrainSchedule, TrainState


class Position(BaseModel):
    latitude: float | None
    longitude: float | None


def _data_age_seconds(retrieved_at: datetime | None) -> float | None:
    if retrieved_at is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - retrieved_at).total_seconds())


class LiveTrainStateResponse(BaseModel):
    train_number: str
    position: Position | None
    speed_kmph: float | None
    station_code: str | None
    section_code: str | None
    delay_minutes: int | None
    event_type: EventType | None
    timestamp: datetime | None
    data_source: ProviderName | None
    data_status: DataStatus
    retrieved_at: datetime | None
    data_age_seconds: float | None
    error: str | None = None
    metadata: dict[str, Any] | None = None
    # Phase 11 Standardized synonym fields
    status: str | None = None
    provider_status: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.status and self.data_status:
            self.status = self.data_status.value if hasattr(self.data_status, "value") else str(self.data_status)
        if not self.provider_status and self.data_source:
            self.provider_status = self.data_source.value if hasattr(self.data_source, "value") else str(self.data_source)

    @classmethod
    def from_result(cls, train_number: str, result: LiveResult[TrainState]) -> "LiveTrainStateResponse":
        state = result.data
        return cls(
            train_number=train_number,
            position=Position(latitude=state.latitude, longitude=state.longitude) if state is not None else None,
            speed_kmph=state.speed_kmph if state is not None else None,
            station_code=state.station_code if state is not None else None,
            section_code=state.section_code if state is not None else None,
            delay_minutes=state.delay_minutes if state is not None else None,
            event_type=state.event_type if state is not None else None,
            timestamp=state.timestamp if state is not None else None,
            data_source=result.actual_provider,
            data_status=result.data_status,
            retrieved_at=result.retrieved_at,
            data_age_seconds=_data_age_seconds(result.retrieved_at),
            error=result.error,
            metadata=state.metadata if state is not None else None,
        )


class LiveTrainRouteStopResponse(BaseModel):
    sequence_number: int
    station_code: str
    station_name: str | None
    arrival_time: time | None
    departure_time: time | None
    distance_km: float | None


class LiveTrainRouteResponse(BaseModel):
    train_number: str
    source: str | None
    destination: str | None
    stations: list[LiveTrainRouteStopResponse]
    data_source: ProviderName | None
    data_status: DataStatus
    retrieved_at: datetime | None
    error: str | None = None

    @classmethod
    def from_result(cls, train_number: str, result: LiveResult[TrainSchedule]) -> "LiveTrainRouteResponse":
        schedule = result.data
        return cls(
            train_number=train_number,
            source=schedule.source if schedule is not None else None,
            destination=schedule.destination if schedule is not None else None,
            stations=(
                [
                    LiveTrainRouteStopResponse(
                        sequence_number=stop.sequence_number,
                        station_code=stop.station_code,
                        station_name=stop.station_name,
                        arrival_time=stop.scheduled_arrival,
                        departure_time=stop.scheduled_departure,
                        distance_km=stop.distance_km,
                    )
                    for stop in schedule.stations
                ]
                if schedule is not None
                else []
            ),
            data_source=result.actual_provider,
            data_status=result.data_status,
            retrieved_at=result.retrieved_at,
            error=result.error,
        )


class LiveStationBoardEntryResponse(BaseModel):
    train_number: str
    train_name: str | None
    scheduled_arrival: time | None
    scheduled_departure: time | None
    delay_minutes: int | None
    status: str | None


class LiveStationBoardResponse(BaseModel):
    station_code: str
    trains: list[LiveStationBoardEntryResponse]
    data_source: ProviderName | None
    data_status: DataStatus
    retrieved_at: datetime | None
    error: str | None = None

    @classmethod
    def from_result(cls, station_code: str, result: LiveResult[StationBoard]) -> "LiveStationBoardResponse":
        board = result.data
        return cls(
            station_code=station_code,
            trains=(
                [
                    LiveStationBoardEntryResponse(
                        train_number=entry.train_number,
                        train_name=entry.train_name,
                        scheduled_arrival=entry.scheduled_arrival,
                        scheduled_departure=entry.scheduled_departure,
                        delay_minutes=entry.delay_minutes,
                        status=entry.status,
                    )
                    for entry in board.trains
                ]
                if board is not None
                else []
            ),
            data_source=result.actual_provider,
            data_status=result.data_status,
            retrieved_at=result.retrieved_at,
            error=result.error,
        )
