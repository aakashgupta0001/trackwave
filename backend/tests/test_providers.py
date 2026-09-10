"""Provider-layer tests that never touch a real external service or the database — the
manager tests use small fake providers injected in place of the real NTES/RailRadar/
Simulator adapters, exactly as the Phase 4 brief requires ("mock provider responses").
"""

from datetime import date, datetime, timezone

import httpx
import pytest

from app.providers.base import (
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RailwayDataProvider,
)
from app.providers.manager import ProviderManager
from app.providers.models import DataStatus, ProviderName, ProviderStatus, StationBoard, TrainSchedule, TrainState
from app.providers.ntes import NTESProvider
from app.providers.railradar import RailRadarProvider

# asyncio_mode = auto (pytest.ini) already handles async test functions; no module-level
# `pytestmark` here since this file also has plain sync tests.


def _train_state(source: ProviderName, **overrides) -> TrainState:
    defaults = dict(
        train_number="12951",
        journey_date=date(2026, 9, 10),
        timestamp=datetime.now(timezone.utc),
        latitude=28.6,
        longitude=77.2,
        speed_kmph=80.0,
        station_code=None,
        section_code="NDLS-MTJ",
        delay_minutes=5,
        data_source=source,
        retrieved_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return TrainState(**defaults)


class FakeProvider(RailwayDataProvider):
    """A provider whose behavior is fully controlled by the test — no network, no DB."""

    def __init__(self, name: ProviderName, *, enabled: bool = True, error: Exception | None = None,
                 delay_seconds: float = 0.0, state: TrainState | None = None):
        self.name = name
        self.enabled = enabled
        self.error = error
        self.delay_seconds = delay_seconds
        self.state = state
        self.call_count = 0

    async def get_train_status(self, session, train_number: str, journey_date: date) -> TrainState:
        import asyncio

        self.call_count += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self.state or _train_state(self.name, train_number=train_number, journey_date=journey_date)

    async def get_train_route(self, session, train_number: str) -> TrainSchedule:
        if self.error is not None:
            raise self.error
        return TrainSchedule(
            train_number=train_number, source="NDLS", destination="CSMT", stations=[],
            data_source=self.name, retrieved_at=datetime.now(timezone.utc),
        )

    async def get_station_status(self, session, station_code: str) -> StationBoard:
        if self.error is not None:
            raise self.error
        return StationBoard(station_code=station_code, timestamp=datetime.now(timezone.utc), trains=[], data_source=self.name)

    async def get_status(self) -> ProviderStatus:
        return ProviderStatus(provider=self.name, enabled=self.enabled, available=self.enabled and self.error is None)


def _manager_with(**providers: FakeProvider) -> ProviderManager:
    mgr = ProviderManager()
    mgr._providers = dict(providers)  # type: ignore[assignment]
    return mgr


# --- 1. provider interface ------------------------------------------------------------

def test_provider_interface_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        RailwayDataProvider()  # type: ignore[abstract]


# --- 2. NTES normalization (always unavailable, by design) ----------------------------

async def test_ntes_always_reports_unavailable() -> None:
    provider = NTESProvider()
    status = await provider.get_status()
    assert status.available is False
    assert status.provider == ProviderName.NTES

    with pytest.raises(ProviderUnavailableError):
        await provider.get_train_status(None, "12951", date.today())


# --- 3. RailRadar normalization ---------------------------------------------------------

async def test_railradar_unconfigured_is_unavailable_and_never_calls_network() -> None:
    provider = RailRadarProvider()
    provider._settings.RAILRADAR_ENABLED = False
    provider._settings.RAILRADAR_API_KEY = ""
    provider._settings.RAILRADAR_BASE_URL = ""
    status = await provider.get_status()
    assert status.enabled is False
    assert status.available is False
    assert status.configured is False

    with pytest.raises(ProviderUnavailableError):
        await provider.get_train_status(None, "12951", date.today())


async def test_railradar_normalizes_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = RailRadarProvider()
    provider._settings.RAILRADAR_ENABLED = True
    provider._settings.RAILRADAR_API_KEY = "test-key"
    provider._settings.RAILRADAR_BASE_URL = "https://example.invalid"

    async def fake_request(path: str) -> dict:
        return {
            "timestamp": "2026-09-10T12:00:00+00:00",
            "latitude": 28.6, "longitude": 77.2, "speed_kmph": 90.0,
            "station_code": None, "section_code": "NDLS-MTJ", "delay_minutes": 4,
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    state = await provider.get_train_status(None, "12951", date(2026, 9, 10))
    assert state.data_source == ProviderName.RAILRADAR
    assert state.section_code == "NDLS-MTJ"
    assert state.delay_minutes == 4


async def test_railradar_malformed_response_raises_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = RailRadarProvider()
    provider._settings.RAILRADAR_ENABLED = True
    provider._settings.RAILRADAR_API_KEY = "test-key"
    provider._settings.RAILRADAR_BASE_URL = "https://example.invalid"

    async def fake_request(path: str) -> dict:
        return {"unexpected": "shape"}  # missing required "timestamp" key

    monkeypatch.setattr(provider, "_request", fake_request)
    with pytest.raises(ProviderDataError):
        await provider.get_train_status(None, "12951", date(2026, 9, 10))


async def test_railradar_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = RailRadarProvider()
    provider._settings.RAILRADAR_ENABLED = True
    provider._settings.RAILRADAR_API_KEY = "test-key"
    provider._settings.RAILRADAR_BASE_URL = "https://example.invalid"
    provider._settings.PROVIDER_TIMEOUT_SECONDS = 0.01

    class _FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): raise httpx.TimeoutException("boom")

    monkeypatch.setattr("app.providers.railradar.httpx.AsyncClient", _FakeClient)
    with pytest.raises(ProviderTimeoutError):
        await provider.get_train_status(None, "12951", date(2026, 9, 10))


# --- 4/5. provider manager: primary success / failure+fallback --------------------------

async def test_manager_primary_success() -> None:
    primary = FakeProvider(ProviderName.RAILRADAR)
    mgr = _manager_with(**{ProviderName.RAILRADAR: primary})
    mgr._settings.PRIMARY_DATA_PROVIDER = "RAILRADAR"
    mgr._settings.FALLBACK_DATA_PROVIDER = ""

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.LIVE
    assert result.actual_provider == ProviderName.RAILRADAR
    assert result.requested_provider == ProviderName.RAILRADAR


async def test_manager_primary_failure_falls_back_when_configured() -> None:
    primary = FakeProvider(ProviderName.NTES, error=ProviderUnavailableError("down"))
    fallback = FakeProvider(ProviderName.RAILRADAR)
    mgr = _manager_with(**{ProviderName.NTES: primary, ProviderName.RAILRADAR: fallback})
    mgr._settings.PRIMARY_DATA_PROVIDER = "NTES"
    mgr._settings.FALLBACK_DATA_PROVIDER = "RAILRADAR"

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.LIVE
    assert result.requested_provider == ProviderName.NTES
    assert result.actual_provider == ProviderName.RAILRADAR  # actual != requested, and surfaced


# --- 6. all providers unavailable --> UNAVAILABLE, never a silent simulator fallback -----

async def test_manager_all_unavailable_never_silently_uses_simulator() -> None:
    primary = FakeProvider(ProviderName.NTES, error=ProviderUnavailableError("down"))
    simulator = FakeProvider(ProviderName.SIMULATOR)  # enabled and healthy, but NOT configured as fallback
    mgr = _manager_with(**{ProviderName.NTES: primary, ProviderName.SIMULATOR: simulator})
    mgr._settings.PRIMARY_DATA_PROVIDER = "NTES"
    mgr._settings.FALLBACK_DATA_PROVIDER = ""  # explicitly no fallback configured

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.UNAVAILABLE
    assert result.actual_provider is None
    assert simulator.call_count == 0  # never invoked


# --- 20. simulator results are always marked SIMULATED, not LIVE ------------------------

async def test_manager_marks_simulator_results_as_simulated() -> None:
    simulator = FakeProvider(ProviderName.SIMULATOR)
    mgr = _manager_with(**{ProviderName.SIMULATOR: simulator})
    mgr._settings.PRIMARY_DATA_PROVIDER = "SIMULATOR"
    mgr._settings.FALLBACK_DATA_PROVIDER = ""

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.SIMULATED
    assert result.actual_provider == ProviderName.SIMULATOR


# --- 13. provider status --------------------------------------------------------------------

async def test_manager_lists_all_provider_statuses() -> None:
    a = FakeProvider(ProviderName.NTES, enabled=False)
    b = FakeProvider(ProviderName.SIMULATOR, enabled=True)
    mgr = _manager_with(**{ProviderName.NTES: a, ProviderName.SIMULATOR: b})

    statuses = await mgr.list_provider_statuses()
    by_name = {s.provider: s for s in statuses}
    assert by_name[ProviderName.NTES].enabled is False
    assert by_name[ProviderName.SIMULATOR].enabled is True


# --- 16. missing provider credentials ----------------------------------------------------

async def test_provider_disabled_is_unavailable_without_being_called() -> None:
    disabled = FakeProvider(ProviderName.NTES, enabled=False)
    mgr = _manager_with(**{ProviderName.NTES: disabled})
    mgr._settings.PRIMARY_DATA_PROVIDER = "NTES"
    mgr._settings.FALLBACK_DATA_PROVIDER = ""

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.UNAVAILABLE
    assert disabled.call_count == 0  # disabled providers are never invoked


# --- 17. provider timeout -----------------------------------------------------------------

async def test_manager_treats_slow_provider_as_timeout() -> None:
    slow = FakeProvider(ProviderName.NTES, delay_seconds=0.2)
    mgr = _manager_with(**{ProviderName.NTES: slow})
    mgr._settings.PRIMARY_DATA_PROVIDER = "NTES"
    mgr._settings.FALLBACK_DATA_PROVIDER = ""
    mgr._settings.PROVIDER_TIMEOUT_SECONDS = 0.02

    result = await mgr.get_train_status(None, "12951", date.today())
    assert result.data_status == DataStatus.UNAVAILABLE
    assert "timed out" in (result.error or "")


# --- provider errors are a proper exception hierarchy -------------------------------------

def test_provider_exception_hierarchy() -> None:
    assert issubclass(ProviderTimeoutError, ProviderUnavailableError)
    assert issubclass(ProviderUnavailableError, ProviderError)
    assert issubclass(ProviderDataError, ProviderError)
    assert issubclass(ProviderNotFoundError, ProviderError)
