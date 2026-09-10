"""Simulator adapter — wraps RAILCAST's own Phase 2 sample data (seeded stations, trains,
routes, and TrainEvent rows) behind the exact same provider interface a real feed would
use, so the rest of the system can't tell the difference at the call site.

Every result is explicitly tagged data_source=SIMULATOR; ProviderManager maps that to
data_status=SIMULATED end-to-end. This adapter must never be mistaken for a live feed —
see the module docstring in app/providers/manager.py for how that separation is enforced.
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.base import ProviderNotFoundError, RailwayDataProvider
from app.providers.models import (
    ProviderName,
    ProviderStatus,
    StationBoard,
    StationBoardEntry,
    TrainSchedule,
    TrainScheduleStop,
    TrainState,
)
from app.repositories import event_repository, route_repository, station_repository, train_repository

logger = logging.getLogger(__name__)


class SimulatorProvider(RailwayDataProvider):
    name = ProviderName.SIMULATOR

    def __init__(self) -> None:
        self._settings = get_settings()
        self._last_success: datetime | None = None
        self._last_failure: datetime | None = None

    async def get_train_status(self, session: AsyncSession, train_number: str, journey_date: date) -> TrainState:
        train = await train_repository.get_by_number(session, train_number)
        if train is None:
            self._last_failure = datetime.now(timezone.utc)
            raise ProviderNotFoundError(f"Simulator has no train {train_number}")

        event = await event_repository.get_latest_for_train(session, train.id)
        if event is None:
            self._last_failure = datetime.now(timezone.utc)
            raise ProviderNotFoundError(f"Simulator has no event data yet for train {train_number}")

        self._last_success = datetime.now(timezone.utc)
        return TrainState(
            train_number=train_number,
            journey_date=journey_date,
            timestamp=event.timestamp,
            latitude=float(event.latitude) if event.latitude is not None else None,
            longitude=float(event.longitude) if event.longitude is not None else None,
            speed_kmph=float(event.speed_kmph) if event.speed_kmph is not None else None,
            station_code=event.station.station_code if event.station is not None else None,
            section_code=event.section.section_code if event.section is not None else None,
            delay_minutes=event.delay_minutes,
            event_type=event.event_type,
            data_source=ProviderName.SIMULATOR,
            retrieved_at=datetime.now(timezone.utc),
            metadata=event.event_metadata,
        )

    async def get_train_route(self, session: AsyncSession, train_number: str) -> TrainSchedule:
        train = await train_repository.get_by_number(session, train_number)
        if train is None:
            self._last_failure = datetime.now(timezone.utc)
            raise ProviderNotFoundError(f"Simulator has no train {train_number}")

        route = await route_repository.list_for_train(session, train.id)
        if not route:
            self._last_failure = datetime.now(timezone.utc)
            raise ProviderNotFoundError(f"Simulator has no route data for train {train_number}")

        self._last_success = datetime.now(timezone.utc)
        return TrainSchedule(
            train_number=train_number,
            source=route[0].station.station_code,
            destination=route[-1].station.station_code,
            stations=[
                TrainScheduleStop(
                    sequence_number=entry.sequence_number,
                    station_code=entry.station.station_code,
                    station_name=entry.station.station_name,
                    scheduled_arrival=entry.scheduled_arrival,
                    scheduled_departure=entry.scheduled_departure,
                    distance_km=float(entry.distance_from_origin_km),
                )
                for entry in route
            ],
            data_source=ProviderName.SIMULATOR,
            retrieved_at=datetime.now(timezone.utc),
        )

    async def get_station_status(self, session: AsyncSession, station_code: str) -> StationBoard:
        station = await station_repository.get_by_code(session, station_code)
        if station is None:
            self._last_failure = datetime.now(timezone.utc)
            raise ProviderNotFoundError(f"Simulator has no station {station_code}")

        routes = await route_repository.list_for_station(session, station.id)
        train_ids = list({route.train_id for route in routes})
        latest_events = await event_repository.get_latest_for_trains(session, train_ids)

        self._last_success = datetime.now(timezone.utc)
        entries = []
        for route in routes:
            event = latest_events.get(route.train_id)
            if event is None:
                status, delay = "NO_RECENT_DATA", None
            elif event.delay_minutes > 0:
                status, delay = "DELAYED", event.delay_minutes
            else:
                status, delay = "ON_TIME", event.delay_minutes
            entries.append(
                StationBoardEntry(
                    train_number=route.train.train_number,
                    train_name=route.train.train_name,
                    scheduled_arrival=route.scheduled_arrival,
                    scheduled_departure=route.scheduled_departure,
                    delay_minutes=delay,
                    status=status,
                )
            )

        return StationBoard(
            station_code=station_code,
            timestamp=datetime.now(timezone.utc),
            trains=entries,
            data_source=ProviderName.SIMULATOR,
        )

    async def get_status(self) -> ProviderStatus:
        enabled = self._settings.SIMULATOR_ENABLED
        return ProviderStatus(
            provider=self.name,
            enabled=enabled,
            # Unlike the real providers, availability doesn't require a proven prior
            # success: the simulator has no external network dependency, only the
            # database — already covered separately by /health.
            available=enabled,
            last_success=self._last_success,
            last_failure=self._last_failure,
            latency_ms=None,
            error=None if enabled else "SIMULATOR_ENABLED is false",
            configured=True,
            provider_type="SIMULATOR",
        )
