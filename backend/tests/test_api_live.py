"""API tests for /api/v1/live/* and /api/v1/providers/* against the real (idempotently
reseeded) Phase 2 sample data. The default config (PRIMARY_DATA_PROVIDER=SIMULATOR) means
these exercise the full ProviderManager pipeline end-to-end, not just the adapter directly.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# --- providers status (no DB/seed required) -----------------------------------------------

async def test_providers_status_lists_all_three(client: AsyncClient) -> None:
    response = await client.get("/api/v1/providers/status")
    assert response.status_code == 200
    body = response.json()
    names = {p["provider"] for p in body["providers"]}
    assert names == {"NTES", "RAILRADAR", "SIMULATOR"}


async def test_providers_status_reflects_default_config(client: AsyncClient) -> None:
    response = await client.get("/api/v1/providers/status")
    by_name = {p["provider"]: p for p in response.json()["providers"]}
    assert by_name["NTES"]["enabled"] is False
    assert by_name["NTES"]["available"] is False
    assert by_name["RAILRADAR"]["enabled"] is False
    assert by_name["RAILRADAR"]["available"] is False
    assert by_name["SIMULATOR"]["enabled"] is True
    assert by_name["SIMULATOR"]["available"] is True
    # never leak anything resembling a credential
    for provider in by_name.values():
        assert "api_key" not in {k.lower() for k in provider}
        assert "authorization" not in {k.lower() for k in provider}


async def test_single_provider_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/providers/SIMULATOR/status")
    assert response.status_code == 200
    assert response.json()["provider"] == "SIMULATOR"


async def test_unknown_provider_status_is_422(client: AsyncClient) -> None:
    response = await client.get("/api/v1/providers/UNKNOWN/status")
    assert response.status_code == 422


# --- live train state ------------------------------------------------------------------------

async def test_live_train_state_is_explicitly_simulated(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/trains/12951")
    assert response.status_code == 200
    body = response.json()

    assert body["train_number"] == "12951"
    assert body["data_source"] == "SIMULATOR"
    assert body["data_status"] == "SIMULATED"
    assert body["section_code"] == "AGC-GWL"
    assert body["delay_minutes"] == 15
    assert body["data_age_seconds"] >= 0
    assert body["retrieved_at"] is not None


async def test_live_train_state_unknown_train_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/trains/99999")
    assert response.status_code == 404
    assert "99999" in response.json()["detail"]


async def test_live_train_state_does_not_calculate_eta(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/trains/12951")
    body = response.json()
    # no ETA-shaped field should ever appear on this endpoint
    for forbidden in ("eta", "predicted_arrival", "final_eta", "baseline_eta"):
        assert forbidden not in body


# --- live train route -------------------------------------------------------------------------

async def test_live_train_route(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/trains/12951/route")
    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "SIMULATOR"
    assert body["data_status"] == "SIMULATED"
    assert body["source"] == "NDLS"
    assert body["destination"] == "CSMT"
    assert len(body["stations"]) == 9


async def test_live_train_route_unknown_train_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/trains/99999/route")
    assert response.status_code == 404


# --- live station board ------------------------------------------------------------------------

async def test_live_station_board(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/stations/BPL")
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "BPL"
    assert body["data_source"] == "SIMULATOR"
    assert body["data_status"] == "SIMULATED"
    train_numbers = {t["train_number"] for t in body["trains"]}
    assert "12294" in train_numbers


async def test_live_station_board_unknown_station_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/live/stations/ZZZZ")
    assert response.status_code == 404


# --- backward compatibility with Phase 3 (module 23) ---------------------------------------------

async def test_phase3_train_state_endpoint_still_works(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/12951/state")
    assert response.status_code == 200
    assert response.json()["event_type"] == "SIGNAL_HALT"
