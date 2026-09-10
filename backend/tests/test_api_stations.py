"""API tests for /api/v1/stations/*, exercised against the real (idempotently reseeded)
Phase 2 sample railway network — see scripts/seed.py.
"""

import pytest
from httpx import AsyncClient

from scripts.seed import STATIONS

pytestmark = pytest.mark.asyncio

STATION_CODES = {s["station_code"] for s in STATIONS}


# --- 14. list stations ------------------------------------------------------------------

async def test_list_stations(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(STATIONS)
    returned_codes = {item["station_code"] for item in body["items"]}
    assert returned_codes == STATION_CODES


# --- 15. station search -----------------------------------------------------------------

async def test_station_search_by_name(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations", params={"search": "Delhi"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["station_code"] == "NDLS"


async def test_station_filter_by_zone(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations", params={"zone": "WCR"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["zone"] == "WCR" for item in body["items"])


# --- 16. get station ---------------------------------------------------------------------

async def test_get_station(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations/NDLS")
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "NDLS"
    assert body["station_name"] == "New Delhi"
    assert body["station_type"] == "TERMINAL"
    assert isinstance(body["latitude"], float)


# --- 17. unknown station returns 404 -------------------------------------------------------

async def test_get_unknown_station_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations/ZZZZ")
    assert response.status_code == 404
    assert "ZZZZ" in response.json()["detail"]


# --- 18. station board --------------------------------------------------------------------

async def test_station_board_distinguishes_known_and_unknown_state(seeded_client: AsyncClient) -> None:
    # BPL is on the route of 5 seeded trains; train 12294 (BPL is its *origin*) has no
    # seeded events, so it must show up as NO_RECENT_DATA rather than a fabricated state.
    response = await seeded_client.get("/api/v1/stations/BPL/board")
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "BPL"

    by_train = {item["train_number"]: item for item in body["board"]}
    assert "12294" in by_train
    assert by_train["12294"]["status"] == "NO_RECENT_DATA"
    assert by_train["12294"]["latest_known_delay_minutes"] is None
    assert by_train["12294"]["latest_event_timestamp"] is None

    # 12951's latest known state (a SIGNAL_HALT elsewhere on its route) still surfaces
    # here as its *general* latest-known state — this board is not station-scoped state.
    assert "12951" in by_train
    assert by_train["12951"]["status"] == "DELAYED"
    assert by_train["12951"]["latest_known_delay_minutes"] == 15


async def test_unknown_station_board_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations/ZZZZ/board")
    assert response.status_code == 404


# --- 19. station trains -------------------------------------------------------------------

async def test_station_trains(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations/BPL/trains")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    returned_numbers = {item["train_number"] for item in body["items"]}
    assert returned_numbers == {"12951", "12002", "12615", "11077", "12294"}
    for item in body["items"]:
        assert item["sequence_number"] >= 1


# --- 20. pagination ------------------------------------------------------------------------

async def test_station_trains_pagination(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations/BPL/trains", params={"page": 1, "page_size": 2})
    body = response.json()
    assert body["total"] == 5
    assert body["total_pages"] == 3
    assert len(body["items"]) == 2


async def test_station_list_pagination(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/stations", params={"page": 1, "page_size": 4})
    body = response.json()
    assert body["total"] == len(STATIONS)
    assert len(body["items"]) == 4
    assert body["total_pages"] == -(-len(STATIONS) // 4)


# --- data integrity --------------------------------------------------------------------------

async def test_station_trains_correctly_map_through_train_route(seeded_client: AsyncClient) -> None:
    """Every train listed at BPL/trains must actually include BPL in its own /route."""
    station_trains = (await seeded_client.get("/api/v1/stations/BPL/trains", params={"page_size": 50})).json()

    for item in station_trains["items"]:
        route = (await seeded_client.get(f"/api/v1/trains/{item['train_number']}/route")).json()
        route_codes = [entry["station_code"] for entry in route["route"]]
        assert "BPL" in route_codes
