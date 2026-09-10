from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any
import uuid

from pydantic import BaseModel, Field

from app.providers.models import TrainState


class StreamEventType(str, Enum):
    TRAIN_UPDATE = "train_update"
    GPS_UPDATE = "gps_update"
    STATION_ARRIVAL = "station_arrival"
    STATION_DEPARTURE = "station_departure"
    SECTION_ENTRY = "section_entry"
    SECTION_EXIT = "section_exit"
    SPEED_RESTRICTION = "speed_restriction"
    PLATFORM_CHANGE = "platform_change"
    SCHEDULE_UPDATE = "schedule_update"


class NormalizedTrainEvent(BaseModel):
    """Canonical event payload ingested into Redis Streams (railcast:train-events)."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: StreamEventType = StreamEventType.TRAIN_UPDATE
    train_number: str
    timestamp: datetime
    current_station_code: str | None = None
    next_station_code: str | None = None
    delay_minutes: float = 0.0
    speed_kmh: float | None = None
    current_lat: float | None = None
    current_lng: float | None = None
    source: str = "ntes"
    raw_data: dict[str, Any] | None = None
    fingerprint: str | None = None

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint of core attributes for idempotency / deduplication."""
        ts_str = self.timestamp.isoformat() if self.timestamp else ""
        raw = f"{self.train_number}:{ts_str}:{self.event_type}:{self.current_station_code}:{self.delay_minutes}:{self.speed_kmh}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()


def normalize_train_state(
    state: TrainState,
    event_type: StreamEventType = StreamEventType.TRAIN_UPDATE,
    source: str | None = None,
) -> NormalizedTrainEvent:
    """Helper converting a provider-layer TrainState into a canonical NormalizedTrainEvent."""
    return NormalizedTrainEvent(
        event_type=event_type,
        train_number=state.train_number,
        timestamp=state.timestamp,
        current_station_code=state.station_code,
        delay_minutes=float(state.delay_minutes or 0),
        speed_kmh=state.speed_kmph,
        current_lat=state.latitude,
        current_lng=state.longitude,
        source=source or (state.data_source.value if hasattr(state.data_source, "value") else str(state.data_source)),
        raw_data=state.metadata or {},
    )


class PredictionUpdatePayload(BaseModel):
    """Payload emitted to railcast:prediction-updates stream and WebSockets."""

    train_number: str
    station_code: str
    scheduled_arrival: datetime | None = None
    baseline_arrival: datetime | None = None
    final_eta: datetime | None = None
    delay_minutes: float = 0.0
    uncertainty_lower: datetime | None = None
    uncertainty_upper: datetime | None = None
    confidence_score: int | None = None
    network_impact_score: int | None = None
    calculation_latency_ms: float = 0.0
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_debounced: bool = False


class WebSocketMessageType(str, Enum):
    PREDICTION_UPDATE = "prediction_update"
    TRAIN_STATE = "train_state"
    NETWORK_ALERT = "network_alert"
    CONGESTION_RISK = "congestion_risk"
    HEARTBEAT = "heartbeat"


class WebSocketEnvelope(BaseModel):
    """Envelope pushed to WebSocket subscribers."""

    topic: str
    event_type: WebSocketMessageType
    type: str | None = None
    train_number: str | None = None
    station_code: str | None = None
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        if not self.type:
            self.type = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        if not self.train_number and isinstance(self.data, dict):
            self.train_number = self.data.get("train_number")
        if not self.station_code and isinstance(self.data, dict):
            self.station_code = self.data.get("station_code")
