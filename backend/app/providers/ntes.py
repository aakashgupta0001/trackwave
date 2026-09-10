"""NTES (National Train Enquiry System) adapter.

DATA REALITY: Indian Railways does not publish a documented, stable public developer API
for NTES. Unofficial wrappers exist but are unverified, unstable, and outside the scope of
what this adapter should silently depend on. Per the Phase 4 brief, this adapter therefore:

  - implements the full RailwayDataProvider interface cleanly,
  - never fabricates or guesses at a live connection,
  - always reports itself UNAVAILABLE,
  - documents exactly what would be required to make it real.

To make this adapter live, you would need: a specific, stable, and licensed/permitted NTES
data interface (official data-sharing agreement, or a vetted internal Railways feed) with a
documented request/response contract, plus its base URL and any required credentials. None
of that is assumed, hardcoded, or guessed here.
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.base import ProviderUnavailableError, RailwayDataProvider
from app.providers.models import ProviderName, ProviderStatus, StationBoard, TrainSchedule, TrainState

logger = logging.getLogger(__name__)

_UNAVAILABLE_REASON = (
    "NTES has no documented public developer API available to this build; no live "
    "interface is configured. See app/providers/ntes.py for what would be required."
)


class NTESProvider(RailwayDataProvider):
    name = ProviderName.NTES

    def __init__(self) -> None:
        self._settings = get_settings()
        self._last_failure: datetime | None = None

    def _fail(self, subject: str) -> None:
        self._last_failure = datetime.now(timezone.utc)
        logger.info("provider=%s subject=%s status=unavailable reason=%r", self.name.value, subject, _UNAVAILABLE_REASON)

    async def get_train_status(self, session: AsyncSession, train_number: str, journey_date: date) -> TrainState:
        self._fail(train_number)
        raise ProviderUnavailableError(_UNAVAILABLE_REASON)

    async def get_train_route(self, session: AsyncSession, train_number: str) -> TrainSchedule:
        self._fail(train_number)
        raise ProviderUnavailableError(_UNAVAILABLE_REASON)

    async def get_station_status(self, session: AsyncSession, station_code: str) -> StationBoard:
        self._fail(station_code)
        raise ProviderUnavailableError(_UNAVAILABLE_REASON)

    async def get_status(self) -> ProviderStatus:
        enabled = self._settings.NTES_ENABLED
        return ProviderStatus(
            provider=self.name,
            enabled=enabled,
            available=False,
            last_success=None,
            last_failure=self._last_failure,
            latency_ms=None,
            error=_UNAVAILABLE_REASON if enabled else "NTES_ENABLED is false",
            configured=False,
            provider_type="REAL",
        )
