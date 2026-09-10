import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_shape(client: AsyncClient) -> None:
    response = await client.get("/health")
    body = response.json()

    assert body["status"] in {"ok", "degraded"}
    assert body["service"] == "RAILCAST"
    assert "version" in body
    assert "timestamp" in body
    assert body["dependencies"]["database"] in {"up", "down"}
    assert body["dependencies"]["redis"] in {"up", "down"}


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "RAILCAST"
