"""Train state updater with out-of-order event handling and deterministic deduplication."""

from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import redis_client as default_redis
from app.core.config import get_settings
from app.models.enums import EventSource, EventType
from app.models.train_event import TrainEvent
from app.repositories import event_repository, section_repository, station_repository, train_repository
from app.schemas.train_event import TrainEventCreate
from app.streaming.schemas import NormalizedTrainEvent

logger = logging.getLogger(__name__)


class ActiveTrainState(BaseModel):
    """Current in-memory operational state of an active train."""

    train_number: str
    last_event_id: str
    last_event_time: datetime
    last_event_type: str
    current_station_code: str | None = None
    next_station_code: str | None = None
    delay_minutes: float = 0.0
    speed_kmh: float | None = None
    current_lat: float | None = None
    current_lng: float | None = None
    prev_delay_minutes: float | None = None
    prev_lat: float | None = None
    prev_lng: float | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TrainStateUpdater:
    """Manages active train states, handles out-of-order event arrivals,

    and enforces deterministic event deduplication.
    """

    def __init__(self, redis: Redis | None = None, max_cache_size: int = 10000) -> None:
        self.settings = get_settings()
        self._redis = redis
        self._max_cache_size = max_cache_size
        self._active_states: dict[str, ActiveTrainState] = {}
        # In-memory bounded LRU cache of fingerprints for fast dedup
        self._seen_fingerprints: OrderedDict[str, float] = OrderedDict()

    @property
    def redis(self) -> Redis:
        return self._redis or default_redis

    def is_duplicate(self, fingerprint: str) -> bool:
        """Check if an event fingerprint has already been processed."""
        if not fingerprint:
            return False
        if fingerprint in self._seen_fingerprints:
            return True
        return False

    def mark_seen(self, fingerprint: str) -> None:
        """Record fingerprint in LRU cache with eviction of oldest."""
        if not fingerprint:
            return
        if len(self._seen_fingerprints) >= self._max_cache_size:
            self._seen_fingerprints.popitem(last=False)
        self._seen_fingerprints[fingerprint] = datetime.now(timezone.utc).timestamp()

    async def get_active_state(self, train_number: str) -> ActiveTrainState | None:
        """Get the latest operational state for a train."""
        if train_number in self._active_states:
            return self._active_states[train_number]

        # Try redis fallback
        try:
            raw = await self.redis.get(f"railcast:train:state:{train_number}")
            if raw:
                state = ActiveTrainState.model_validate_json(raw)
                self._active_states[train_number] = state
                return state
        except Exception:
            pass

        return None

    async def persist_train_event(
        self, session: AsyncSession, event: NormalizedTrainEvent
    ) -> TrainEvent | None:
        """Persist the event to PostgreSQL train_events table.

        Always records incoming events historically, even if out-of-order.
        """
        train = await train_repository.get_by_number(session, event.train_number)
        if train is None:
            logger.warning("TrainStateUpdater: unknown train %s; skipping DB write", event.train_number)
            return None

        # Resolve event source
        try:
            event_source = EventSource(event.source.upper())
        except Exception:
            event_source = EventSource.NTES

        # Deduplicate at DB level
        existing = await event_repository.find_duplicate(
            session, train.id, event_source, event.timestamp
        )
        if existing is not None:
            return existing

        station = None
        if event.current_station_code:
            station = await station_repository.get_by_code(session, event.current_station_code)

        event_type = EventType.POSITION_UPDATE
        # Match common event types
        ev_name = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        if "arrival" in ev_name.lower():
            event_type = EventType.ARRIVAL
        elif "departure" in ev_name.lower():
            event_type = EventType.DEPARTURE
        elif "speed" in ev_name.lower():
            event_type = EventType.SPEED_RESTRICTION

        lat = Decimal(str(event.current_lat)) if event.current_lat is not None else None
        lng = Decimal(str(event.current_lng)) if event.current_lng is not None else None
        speed = Decimal(str(event.speed_kmh)) if event.speed_kmh is not None else None

        db_event = await event_repository.create(
            session,
            TrainEventCreate(
                train_id=train.id,
                timestamp=event.timestamp,
                latitude=lat,
                longitude=lng,
                speed_kmph=speed,
                station_id=station.id if station else None,
                section_id=None,
                delay_minutes=int(event.delay_minutes),
                event_type=event_type,
                event_source=event_source,
                metadata=event.raw_data or {},
            ),
        )
        await session.commit()
        return db_event

    async def process_event(
        self, session: AsyncSession, event: NormalizedTrainEvent
    ) -> tuple[bool, ActiveTrainState | None, TrainEvent | None]:
        """Process an incoming normalized train event with out-of-order handling.

        Returns:
            (is_operational_update, active_state, db_event)
            - is_operational_update: True if this event advanced the operational state,
              False if duplicate or out-of-order.
            - active_state: Latest operational state for the train.
            - db_event: The persisted TrainEvent (committed to DB).
        """
        fingerprint = event.fingerprint or event.compute_fingerprint()

        # Check deduplication
        if self.is_duplicate(fingerprint):
            logger.debug("Duplicate event %s for train %s ignored", fingerprint, event.train_number)
            current = await self.get_active_state(event.train_number)
            return False, current, None

        self.mark_seen(fingerprint)

        # 1. ALWAYS persist event to database historical log
        db_event = await self.persist_train_event(session, event)

        # 2. Check out-of-order arrival against current active state
        current = await self.get_active_state(event.train_number)

        ev_type_str = (
            event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        )

        if current is not None:
            # Ensure comparable timestamps (timezone-aware/naive handling)
            event_ts = event.timestamp
            curr_ts = current.last_event_time
            if event_ts.tzinfo is not None and curr_ts.tzinfo is None:
                curr_ts = curr_ts.replace(tzinfo=event_ts.tzinfo)
            elif event_ts.tzinfo is None and curr_ts.tzinfo is not None:
                event_ts = event_ts.replace(tzinfo=curr_ts.tzinfo)

            if event_ts < curr_ts:
                # Out-of-order event!
                # We do NOT advance the current state, but DB event is already saved.
                logger.info(
                    "Out-of-order event for train %s: event_ts=%s < current_ts=%s. "
                    "Recorded in DB but skipped operational state overwrite.",
                    event.train_number,
                    event.timestamp.isoformat(),
                    current.last_event_time.isoformat(),
                )
                return False, current, db_event

        # 3. Newer or initial event -> advance operational state
        new_state = ActiveTrainState(
            train_number=event.train_number,
            last_event_id=event.event_id,
            last_event_time=event.timestamp,
            last_event_type=ev_type_str,
            current_station_code=event.current_station_code or (current.current_station_code if current else None),
            next_station_code=event.next_station_code or (current.next_station_code if current else None),
            delay_minutes=event.delay_minutes,
            speed_kmh=event.speed_kmh,
            current_lat=event.current_lat,
            current_lng=event.current_lng,
            prev_delay_minutes=current.delay_minutes if current else None,
            prev_lat=current.current_lat if current else None,
            prev_lng=current.current_lng if current else None,
            updated_at=datetime.now(timezone.utc),
        )

        self._active_states[event.train_number] = new_state

        # Update Redis cache best-effort
        try:
            await self.redis.set(
                f"railcast:train:state:{event.train_number}",
                new_state.model_dump_json(),
                ex=3600,
            )
        except Exception:
            pass

        return True, new_state, db_event


# Shared singleton
train_state_updater = TrainStateUpdater()
