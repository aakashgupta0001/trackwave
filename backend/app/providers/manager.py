"""ProviderManager: the one place that knows about primary/fallback selection, timeouts,
per-provider cooldown, and Redis caching. Everything else in the system — live API routes,
the ingestion worker — calls this, never a provider adapter directly.

SAFETY RULE (Phase 4 spec, module 9): if the primary provider fails, the manager tries
FALLBACK_DATA_PROVIDER *only if it is explicitly configured*. It never silently substitutes
the simulator (or any other provider) as an implicit fallback — a production deployment
must not accidentally present simulated positions as real ones. If nothing configured
succeeds, the result is UNAVAILABLE, not a quiet swap to fabricated data.

CACHING (module 11): each cache entry is written with a hard Redis TTL of
4x PROVIDER_CACHE_TTL_SECONDS, but treated as fresh (LIVE/SIMULATED) only within
PROVIDER_CACHE_TTL_SECONDS of its retrieval. Once past that softer freshness window but
still within the hard TTL, a fresh provider call is attempted; if that also fails, the old
entry is returned anyway but relabeled STALE rather than silently claiming LIVE. Once the
hard TTL passes, Redis evicts the entry entirely and a full cache miss occurs.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import redis_client
from app.core.config import get_settings
from app.providers.base import (
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RailwayDataProvider,
)
from app.providers.models import DataStatus, ProviderName, ProviderStatus, StationBoard, TrainSchedule, TrainState
from app.providers.ntes import NTESProvider
from app.providers.railradar import RailRadarProvider
from app.providers.simulator import SimulatorProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LiveResult(BaseModel, Generic[T]):
    """What every ProviderManager call returns — the API layer flattens this into the
    module-15 JSON envelope; the ingestion worker reads `.data`/`.data_status` directly.
    """

    data: T | None
    data_status: DataStatus
    requested_provider: ProviderName | None
    actual_provider: ProviderName | None
    retrieved_at: datetime | None
    error: str | None = None


class ProviderManager:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._providers: dict[ProviderName, RailwayDataProvider] = {
            ProviderName.NTES: NTESProvider(),
            ProviderName.RAILRADAR: RailRadarProvider(),
            ProviderName.SIMULATOR: SimulatorProvider(),
        }
        self._cooldown_until: dict[ProviderName, datetime] = {}

    # --- provider selection -------------------------------------------------------

    def _resolve(self, raw: str) -> ProviderName | None:
        if not raw:
            return None
        try:
            return ProviderName(raw.upper())
        except ValueError:
            logger.warning("Unknown provider name in configuration: %r", raw)
            return None

    @property
    def primary(self) -> ProviderName | None:
        return self._resolve(self._settings.PRIMARY_DATA_PROVIDER)

    @property
    def fallback(self) -> ProviderName | None:
        return self._resolve(self._settings.FALLBACK_DATA_PROVIDER)

    # --- cooldown (basic circuit breaker, module 12) -------------------------------

    def _in_cooldown(self, name: ProviderName) -> bool:
        until = self._cooldown_until.get(name)
        return until is not None and datetime.now(timezone.utc) < until

    def _set_cooldown(self, name: ProviderName) -> None:
        self._cooldown_until[name] = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.PROVIDER_COOLDOWN_SECONDS
        )

    # --- caching --------------------------------------------------------------------

    def _cache_key(self, kind: str, *parts: str) -> str:
        return "railcast:live:" + ":".join([kind, *parts])

    async def _read_cache(self, key: str, model_cls: type[T]) -> tuple[T, ProviderName, datetime] | None:
        try:
            raw = await redis_client.get(key)
        except Exception as exc:
            logger.warning("Redis unavailable while reading cache key=%s (%s)", key, type(exc).__name__)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            data = model_cls.model_validate(payload["data"])
            provider = ProviderName(payload["provider"])
            retrieved_at = datetime.fromisoformat(payload["retrieved_at"])
            return data, provider, retrieved_at
        except Exception:
            logger.warning("Discarding unreadable cache entry key=%s", key)
            return None

    async def _write_cache(self, key: str, data: T, provider: ProviderName, retrieved_at: datetime) -> None:
        payload = {"data": data.model_dump(mode="json"), "provider": provider.value, "retrieved_at": retrieved_at.isoformat()}
        ttl = self._settings.PROVIDER_CACHE_TTL_SECONDS * 4
        try:
            await redis_client.set(key, json.dumps(payload), ex=ttl)
        except Exception as exc:
            logger.warning("Redis unavailable while writing cache key=%s (%s)", key, type(exc).__name__)

    # --- provider invocation ---------------------------------------------------------

    async def _fetch_from_provider(
        self, provider_name: ProviderName, session: AsyncSession, call: Callable[[RailwayDataProvider, AsyncSession], Awaitable[T]]
    ) -> T:
        provider = self._providers[provider_name]

        status = await provider.get_status()
        if not status.enabled:
            raise ProviderUnavailableError(f"{provider_name.value} is not enabled")
        if self._in_cooldown(provider_name):
            raise ProviderUnavailableError(f"{provider_name.value} is in cooldown after a recent failure")

        try:
            result = await asyncio.wait_for(call(provider, session), timeout=self._settings.PROVIDER_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            self._set_cooldown(provider_name)
            raise ProviderTimeoutError(f"{provider_name.value} timed out after {self._settings.PROVIDER_TIMEOUT_SECONDS}s") from exc
        except (ProviderNotFoundError, ProviderDataError):
            raise  # per-request issues, not provider health — no cooldown
        except ProviderError:
            self._set_cooldown(provider_name)
            raise
        except Exception as exc:
            self._set_cooldown(provider_name)
            raise ProviderUnavailableError(f"{provider_name.value} failed: {type(exc).__name__}") from exc

        return result

    # --- the shared cache+fallback pipeline -----------------------------------------

    async def _execute(
        self,
        session: AsyncSession,
        cache_kind: str,
        cache_parts: tuple[str, ...],
        model_cls: type[T],
        call: Callable[[RailwayDataProvider, AsyncSession], Awaitable[T]],
    ) -> LiveResult[T]:
        key = self._cache_key(cache_kind, *cache_parts)
        primary = self.primary
        fallback = self.fallback
        now = datetime.now(timezone.utc)

        cached = await self._read_cache(key, model_cls)
        if cached is not None:
            data, cached_provider, retrieved_at = cached
            age = (now - retrieved_at).total_seconds()
            if age <= self._settings.PROVIDER_CACHE_TTL_SECONDS:
                status = DataStatus.SIMULATED if cached_provider == ProviderName.SIMULATOR else DataStatus.LIVE
                return LiveResult(
                    data=data, data_status=status, requested_provider=primary,
                    actual_provider=cached_provider, retrieved_at=retrieved_at,
                )
        else:
            data, cached_provider, retrieved_at = None, None, None

        candidates = [p for p in (primary, fallback) if p is not None]
        last_error: str | None = None
        for candidate in candidates:
            try:
                fresh = await self._fetch_from_provider(candidate, session, call)
            except ProviderError as exc:
                last_error = str(exc)
                logger.warning("provider=%s status=failure cache_kind=%s error=%s", candidate.value, cache_kind, last_error)
                continue

            fresh_retrieved_at = datetime.now(timezone.utc)
            await self._write_cache(key, fresh, candidate, fresh_retrieved_at)
            status = DataStatus.SIMULATED if candidate == ProviderName.SIMULATOR else DataStatus.LIVE
            logger.info("provider=%s status=success cache_kind=%s", candidate.value, cache_kind)
            return LiveResult(
                data=fresh, data_status=status, requested_provider=primary,
                actual_provider=candidate, retrieved_at=fresh_retrieved_at,
            )

        if data is not None:
            logger.info("provider=%s status=stale_fallback cache_kind=%s", cached_provider.value, cache_kind)
            return LiveResult(
                data=data, data_status=DataStatus.STALE, requested_provider=primary,
                actual_provider=cached_provider, retrieved_at=retrieved_at, error=last_error,
            )

        return LiveResult(
            data=None, data_status=DataStatus.UNAVAILABLE, requested_provider=primary,
            actual_provider=None, retrieved_at=None, error=last_error or "No data provider is configured",
        )

    # --- public API -------------------------------------------------------------------

    async def get_train_status(self, session: AsyncSession, train_number: str, journey_date: date) -> LiveResult[TrainState]:
        return await self._execute(
            session, "train", (train_number, journey_date.isoformat()), TrainState,
            lambda provider, s: provider.get_train_status(s, train_number, journey_date),
        )

    async def get_train_route(self, session: AsyncSession, train_number: str) -> LiveResult[TrainSchedule]:
        return await self._execute(
            session, "route", (train_number,), TrainSchedule,
            lambda provider, s: provider.get_train_route(s, train_number),
        )

    async def get_station_status(self, session: AsyncSession, station_code: str) -> LiveResult[StationBoard]:
        return await self._execute(
            session, "station", (station_code,), StationBoard,
            lambda provider, s: provider.get_station_status(s, station_code),
        )

    async def get_provider_status(self, provider_name: ProviderName) -> ProviderStatus:
        return await self._providers[provider_name].get_status()

    async def list_provider_statuses(self) -> list[ProviderStatus]:
        return [await provider.get_status() for provider in self._providers.values()]


provider_manager = ProviderManager()
