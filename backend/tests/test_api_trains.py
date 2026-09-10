"""API tests for /api/v1/trains/*, exercised against the real (idempotently reseeded)
Phase 2 sample railway network — see scripts/seed.py for the exact trains/routes/events
this relies on. No external railway API involved.
"""

import pytest
from httpx import AsyncClient

from scripts.seed import TRAINS

pytestmark = pytest.mark.asyncio

TRAIN_NUMBERS = {t["train_number"] for t in TRAINS}


# --- 1. list trains -----------------------------------------------------------------

async def test_list_trains(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(TRAINS)
    assert body["total_pages"] == 1
    returned_numbers = {item["train_number"] for item in body["items"]}
    assert returned_numbers == TRAIN_NUMBERS


# --- 2. pagination --------------------------------------------------------------------

async def test_train_pagination(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains", params={"page": 1, "page_size": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert len(body["items"]) == 3
    assert body["total_pages"] == -(-body["total"] // 3)

    response_p2 = await seeded_client.get("/api/v1/trains", params={"page": 2, "page_size": 3})
    body_p2 = response_p2.json()
    page1_numbers = {item["train_number"] for item in body["items"]}
    page2_numbers = {item["train_number"] for item in body_p2["items"]}
    assert page1_numbers.isdisjoint(page2_numbers)


async def test_train_pagination_rejects_invalid_params(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains", params={"page": 0})
    assert response.status_code == 422

    response = await seeded_client.get("/api/v1/trains", params={"page_size": 1000})
    assert response.status_code == 422


# --- 3. search by train number ----------------------------------------------------------

async def test_search_trains_by_number(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains", params={"search": "12951"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["train_number"] == "12951"


# --- 4. search by train name -------------------------------------------------------------

async def test_search_trains_by_name(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains", params={"search": "Rajdhani"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all("Rajdhani" in item["train_name"] for item in body["items"])


# --- 5. filter active trains --------------------------------------------------------------

async def test_filter_active_trains(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains", params={"active": True})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(TRAINS)
    assert all(item["active"] is True for item in body["items"])


# --- 6. get train by number ----------------------------------------------------------------

async def test_get_train_by_number(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/12951")
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    assert body["train_name"] == "Mumbai Rajdhani Express"
    assert body["source_station_code"] == "NDLS"
    assert body["destination_station_code"] == "CSMT"
    assert body["route_summary"]["total_stations"] == 9


# --- 7. unknown train returns 404 -----------------------------------------------------------

async def test_get_unknown_train_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/99999")
    assert response.status_code == 404
    assert "99999" in response.json()["detail"]


# --- 8. route ordering -----------------------------------------------------------------------

async def test_train_route_is_ordered_by_sequence(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/12951/route")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "NDLS"
    assert body["destination"] == "CSMT"
    sequence_numbers = [item["sequence_number"] for item in body["route"]]
    assert sequence_numbers == sorted(sequence_numbers)
    assert [item["station_code"] for item in body["route"]] == [
        "NDLS", "MTJ", "AGC", "GWL", "JHS", "BPL", "ET", "NGP", "CSMT",
    ]
    assert body["route"][0]["arrival_time"] is None  # origin has no arrival
    assert body["route"][-1]["departure_time"] is None  # terminus has no departure


async def test_unknown_train_route_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/99999/route")
    assert response.status_code == 404


# --- 9. upcoming route -------------------------------------------------------------------------

async def test_upcoming_route_for_train_with_known_position(seeded_client: AsyncClient) -> None:
    # Train 11077's latest seeded event is a SPEED_RESTRICTION in section GWL-JHS —
    # i.e. it's between GWL and JHS, heading toward JHS.
    response = await seeded_client.get("/api/v1/trains/11077/upcoming")
    assert response.status_code == 200
    body = response.json()
    assert body["has_known_state"] is True
    assert body["current_section_code"] == "GWL-JHS"
    upcoming_codes = [item["station_code"] for item in body["upcoming"]]
    assert upcoming_codes == ["JHS", "BPL", "ET"]


async def test_upcoming_route_for_train_with_no_events_returns_full_route(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/14217/upcoming")
    assert response.status_code == 200
    body = response.json()
    assert body["has_known_state"] is False
    assert body["as_of"] is None
    assert [item["station_code"] for item in body["upcoming"]] == ["NDLS", "MTJ", "AGC"]


# --- 10. latest state selection -----------------------------------------------------------------

async def test_train_state_returns_latest_event(seeded_client: AsyncClient) -> None:
    # Train 12951 has 3 seeded events; the SIGNAL_HALT one is the most recent.
    response = await seeded_client.get("/api/v1/trains/12951/state")
    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "SIGNAL_HALT"
    assert body["section_code"] == "AGC-GWL"
    assert body["delay_minutes"] == 15
    assert body["data_freshness_seconds"] >= 0


# --- 11. train with no events -----------------------------------------------------------------

async def test_train_state_with_no_events_returns_404(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/14217/state")
    assert response.status_code == 404
    assert "14217" in response.json()["detail"]


# --- 12. event pagination --------------------------------------------------------------------

async def test_train_events_pagination(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/12951/events", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    # newest first
    timestamps = [item["timestamp"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)

    response_p2 = await seeded_client.get("/api/v1/trains/12951/events", params={"page": 2, "page_size": 2})
    assert len(response_p2.json()["items"]) == 1


# --- 13. event timestamp filtering -------------------------------------------------------------

async def test_train_events_timestamp_filtering(seeded_client: AsyncClient) -> None:
    all_events = (await seeded_client.get("/api/v1/trains/12951/events", params={"page_size": 50})).json()["items"]
    assert len(all_events) == 3
    # events are newest-first; use the middle one's timestamp as the lower bound
    boundary = all_events[1]["timestamp"]

    response = await seeded_client.get(
        "/api/v1/trains/12951/events", params={"from_timestamp": boundary, "page_size": 50}
    )
    body = response.json()
    assert body["total"] == 2
    assert all(item["timestamp"] >= boundary for item in body["items"])


async def test_train_events_type_filtering(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get(
        "/api/v1/trains/12951/events", params={"event_type": "SIGNAL_HALT", "page_size": 50}
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "SIGNAL_HALT"


# --- data integrity ------------------------------------------------------------------------------

async def test_upcoming_does_not_include_already_passed_stations(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/v1/trains/11077/upcoming")
    upcoming_codes = {item["station_code"] for item in response.json()["upcoming"]}
    assert "AGC" not in upcoming_codes
    assert "GWL" not in upcoming_codes


async def test_latest_state_matches_newest_event_from_events_endpoint(seeded_client: AsyncClient) -> None:
    state = (await seeded_client.get("/api/v1/trains/12951/state")).json()
    events = (await seeded_client.get("/api/v1/trains/12951/events", params={"page_size": 1})).json()
    assert state["timestamp"] == events["items"][0]["timestamp"]
    assert state["event_type"] == events["items"][0]["event_type"]
