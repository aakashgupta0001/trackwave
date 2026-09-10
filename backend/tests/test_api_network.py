"""API tests for /api/v1/network/* (module 43) against the real seeded network.

Kept deliberately lean: every /network/* endpoint currently recomputes the full graph
analysis per call in this dev environment (no Redis => the snapshot cache never hits),
so each test here is expensive (~15-80s). Correctness of the underlying analysis is
covered in more depth, more cheaply, by test_network_impact.py (direct service calls).
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_train_impact_endpoint_shape(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/trains/12951/impact")
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    # Not a hardcoded exact value: this dev database is shared with other concurrent
    # tooling, so only "12951 has a positive known delay" (the seed scenario's intent)
    # is asserted, not the precise minute count at whatever moment this test runs.
    assert body["source_delay_minutes"] > 0
    assert 0 <= body["network_impact_score"] <= 100
    assert body["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "generated_at" in body
    assert isinstance(body["conflicts"], list)


async def test_train_impact_unknown_train_returns_404(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/trains/99999/impact")
    assert response.status_code == 404


async def test_train_with_no_delay_returns_200_zero_impact(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/trains/14217/impact")
    assert response.status_code == 200
    body = response.json()
    assert body["source_delay_minutes"] == 0.0
    assert body["network_impact_score"] == 0


async def test_network_overview_shape(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/overview")
    assert response.status_code == 200
    body = response.json()
    for field in (
        "total_trains_monitored", "delayed_trains", "affected_trains", "affected_stations",
        "affected_sections", "active_conflicts", "hotspots", "network_impact_score",
        "severity", "generated_at", "horizon_minutes",
    ):
        assert field in body
    assert body["horizon_minutes"] == 180


async def test_affected_trains_pagination(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/affected-trains", params={"page": 1, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) <= 2
    assert body["total"] >= len(body["items"])


async def test_affected_trains_severity_filter(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/affected-trains", params={"severity": "CRITICAL"})
    assert response.status_code == 200
    body = response.json()
    assert all(item["impact_severity"] == "CRITICAL" for item in body["items"])


async def test_conflicts_endpoint_and_train_filter(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/conflicts", params={"train_number": "12951"})
    assert response.status_code == 200
    body = response.json()
    for item in body["items"]:
        assert "12951" in (item["train_a"], item["train_b"])


async def test_hotspots_endpoint(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/hotspots")
    assert response.status_code == 200
    hotspots = response.json()
    assert isinstance(hotspots, list)
    for h in hotspots:
        assert h["entity_type"] in ("STATION", "SECTION")


async def test_timeline_endpoint(eta_client: AsyncClient) -> None:
    response = await eta_client.get("/api/v1/network/timeline", params={"bucket_minutes": 60})
    assert response.status_code == 200
    buckets = response.json()
    assert isinstance(buckets, list)
    assert len(buckets) == 3  # 180-minute default horizon / 60-minute buckets
