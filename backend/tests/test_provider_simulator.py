"""Simulator provider tests against the real (idempotently reseeded) Phase 2 sample data.
"""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import ProviderNotFoundError
from app.providers.models import DataStatus, ProviderName
from app.providers.simulator import SimulatorProvider

pytestmark = pytest.mark.asyncio


async def test_simulator_normalizes_latest_event_as_train_state(seeded_session: AsyncSession) -> None:
    provider = SimulatorProvider()
    # Train 12951's latest seeded event is a SIGNAL_HALT in section AGC-GWL.
    state = await provider.get_train_status(seeded_session, "12951", date.today())

    assert state.data_source == ProviderName.SIMULATOR
    assert state.section_code == "AGC-GWL"
    assert state.delay_minutes == 15
    assert state.event_type.value == "SIGNAL_HALT"


async def test_simulator_raises_not_found_for_unknown_train(seeded_session: AsyncSession) -> None:
    provider = SimulatorProvider()
    with pytest.raises(ProviderNotFoundError):
        await provider.get_train_status(seeded_session, "99999", date.today())


async def test_simulator_raises_not_found_for_train_with_no_events(seeded_session: AsyncSession) -> None:
    provider = SimulatorProvider()
    with pytest.raises(ProviderNotFoundError):
        await provider.get_train_status(seeded_session, "14217", date.today())


async def test_simulator_route_matches_seeded_route(seeded_session: AsyncSession) -> None:
    provider = SimulatorProvider()
    schedule = await provider.get_train_route(seeded_session, "12951")
    assert schedule.source == "NDLS"
    assert schedule.destination == "CSMT"
    assert schedule.data_source == ProviderName.SIMULATOR
    assert [s.station_code for s in schedule.stations][:3] == ["NDLS", "MTJ", "AGC"]


async def test_simulator_station_board(seeded_session: AsyncSession) -> None:
    provider = SimulatorProvider()
    board = await provider.get_station_status(seeded_session, "BPL")
    assert board.data_source == ProviderName.SIMULATOR
    train_numbers = {t.train_number for t in board.trains}
    assert "12294" in train_numbers  # no events -> NO_RECENT_DATA, not fabricated

    by_number = {t.train_number: t for t in board.trains}
    assert by_number["12294"].status == "NO_RECENT_DATA"
    assert by_number["12294"].delay_minutes is None


async def test_manager_uses_simulator_by_default_against_real_data(seeded_client: AsyncClient) -> None:
    """End-to-end: default config (PRIMARY_DATA_PROVIDER=SIMULATOR) actually reads real
    seeded data through the full ProviderManager pipeline, not just the adapter directly.
    """
    from app.providers.manager import provider_manager
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await provider_manager.get_train_status(session, "12951", date.today())

    assert result.data_status == DataStatus.SIMULATED
    assert result.actual_provider == ProviderName.SIMULATOR
    assert result.data is not None
    assert result.data.section_code == "AGC-GWL"
