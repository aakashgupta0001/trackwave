from abc import ABC, abstractmethod
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.models import ProviderName, ProviderStatus, StationBoard, TrainSchedule, TrainState


class ProviderError(Exception):
    """Base class for all provider-layer failures."""


class ProviderUnavailableError(ProviderError):
    """The provider is disabled, unconfigured, unreachable, or in cooldown after a
    recent failure. A systemic issue — triggers ProviderManager's cooldown/fallback.
    """


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider call exceeded PROVIDER_TIMEOUT_SECONDS."""


class ProviderDataError(ProviderError):
    """The provider responded, but its data couldn't be normalized/validated. A data
    quality issue for this one request — does NOT trigger cooldown.
    """


class ProviderNotFoundError(ProviderError):
    """The provider is working, but has no data for the requested train/station. A
    per-request issue — does NOT trigger cooldown.
    """


class RailwayDataProvider(ABC):
    """Common interface every real or simulated data source implements. The rest of the
    system (ProviderManager, ingestion, live APIs) only ever talks to this interface —
    never to a provider's raw response format.
    """

    name: ProviderName

    @abstractmethod
    async def get_train_status(self, session: AsyncSession, train_number: str, journey_date: date) -> TrainState:
        """Raise ProviderUnavailableError/ProviderTimeoutError/ProviderDataError/
        ProviderNotFoundError on failure — never return a partially-fabricated TrainState.
        """

    @abstractmethod
    async def get_train_route(self, session: AsyncSession, train_number: str) -> TrainSchedule: ...

    @abstractmethod
    async def get_station_status(self, session: AsyncSession, station_code: str) -> StationBoard: ...

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Must never raise — reflects current known health, not a live probe."""
