"""Normalized data models shared by every provider adapter.

These are intentionally separate from app/schemas — those are the RAILCAST *API* contract
(station codes, frontend-shaped), while these are the *provider* contract: whatever a real
or simulated data source hands back, normalized to one shape before anything else in the
system touches it. Nothing outside app/providers/ should know a provider's raw response
format.
"""

from datetime import date, datetime, time
from enum import Enum

from pydantic import BaseModel

from app.models.enums import EventType


class ProviderName(str, Enum):
    """The providers RAILCAST actually has adapters for. Narrower than
    app.models.enums.EventSource (which also covers non-provider sources like MANUAL/GPS
    entry) — every ProviderName is a valid EventSource, used as-is when ingesting into
    TrainEvent.event_source.
    """

    NTES = "NTES"
    RAILRADAR = "RAILRADAR"
    SIMULATOR = "SIMULATOR"


class DataStatus(str, Enum):
    """How trustworthy/fresh a live-data response is. Every live endpoint response
    carries one of these — never implied, never omitted.
    """

    LIVE = "LIVE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    SIMULATED = "SIMULATED"


class TrainState(BaseModel):
    """Normalized train position/status, as returned by any provider adapter."""

    train_number: str
    journey_date: date
    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    speed_kmph: float | None = None
    station_code: str | None = None
    section_code: str | None = None
    delay_minutes: int | None = None
    event_type: EventType = EventType.POSITION_UPDATE
    data_source: ProviderName
    retrieved_at: datetime
    metadata: dict | None = None


class TrainScheduleStop(BaseModel):
    sequence_number: int
    station_code: str
    station_name: str | None = None
    scheduled_arrival: time | None = None
    scheduled_departure: time | None = None
    distance_km: float | None = None


class TrainSchedule(BaseModel):
    """Normalized train route/schedule, as returned by any provider adapter.

    Serves both `get_train_schedule` and `get_train_route` from the spec's provider
    interface sketch: Phase 4 exposes exactly one live route endpoint, so a second
    near-identical `TrainRouteData` type would be unused duplication — kept as one
    method/model instead.
    """

    train_number: str
    source: str
    destination: str
    stations: list[TrainScheduleStop]
    data_source: ProviderName
    retrieved_at: datetime


class StationBoardEntry(BaseModel):
    train_number: str
    train_name: str | None = None
    scheduled_arrival: time | None = None
    scheduled_departure: time | None = None
    delay_minutes: int | None = None
    status: str | None = None


class StationBoard(BaseModel):
    """Normalized station board, as returned by any provider adapter."""

    station_code: str
    timestamp: datetime
    trains: list[StationBoardEntry]
    data_source: ProviderName


class ProviderStatus(BaseModel):
    """Public provider health contract — never include credentials/tokens here."""

    provider: ProviderName
    enabled: bool
    available: bool
    last_success: datetime | None = None
    last_failure: datetime | None = None
    latency_ms: float | None = None
    error: str | None = None
    configured: bool = False
    provider_type: str = "REAL"
