"""Tests for Phase 10 system health, readiness, liveness, data quality, drift, and metrics."""

import pytest
from httpx import AsyncClient

from app.monitoring.data_quality import data_quality_tracker
from app.monitoring.drift import calculate_ks_test, calculate_psi
from app.monitoring.health import check_liveness, check_readiness, check_system_health


@pytest.mark.asyncio
async def test_liveness_probe():
    resp = check_liveness()
    assert resp.alive is True
    assert resp.timestamp is not None


@pytest.mark.asyncio
async def test_readiness_probe():
    ready, resp = await check_readiness()
    assert isinstance(ready, bool)
    assert "database_connected" in resp.checks


@pytest.mark.asyncio
async def test_system_health_deep_check():
    health = await check_system_health()
    assert health.status in ("HEALTHY", "DEGRADED", "UNAVAILABLE")
    assert "database" in health.components
    assert "redis" in health.components
    assert "streaming" in health.components
    assert "model" in health.components


def test_data_quality_score_calculation():
    tracker = data_quality_tracker
    # Reset counters for testing
    tracker.total_events = 100
    tracker.missing_coordinates = 5
    tracker.invalid_coordinates = 1
    tracker.missing_speed = 2
    tracker.missing_delay = 0
    tracker.stale_events = 4
    tracker.duplicate_events = 3
    tracker.out_of_order_events = 1

    dq = tracker.compute_data_quality_score()
    assert 0.0 <= dq.score <= 100.0
    assert dq.rating.value in ("HIGH", "MEDIUM", "LOW")
    assert dq.completeness.score <= 25.0
    assert dq.freshness.score <= 25.0
    assert dq.validity.score <= 25.0
    assert dq.consistency.score <= 25.0


def test_statistical_drift_psi_and_ks():
    import numpy as np

    np.random.seed(42)
    ref = np.random.normal(loc=10.0, scale=2.0, size=500)

    # Identical distribution -> low PSI, high KS p-value (no drift)
    same_dist = np.random.normal(loc=10.0, scale=2.0, size=500)
    psi_no_drift = calculate_psi(ref, same_dist)
    ks_stat_no, ks_p_no = calculate_ks_test(ref, same_dist)
    assert psi_no_drift < 0.10
    assert ks_p_no > 0.05

    # Shifted distribution -> high PSI, low KS p-value (drift detected)
    shifted_dist = np.random.normal(loc=25.0, scale=5.0, size=500)
    psi_drift = calculate_psi(ref, shifted_dist)
    ks_stat_yes, ks_p_yes = calculate_ks_test(ref, shifted_dist)
    assert psi_drift > 0.20
    assert ks_p_yes < 0.01


@pytest.mark.asyncio
async def test_monitoring_api_endpoints(client: AsyncClient):
    # Liveness
    resp_live = await client.get("/api/v1/system/liveness")
    assert resp_live.status_code == 200
    assert resp_live.json()["alive"] is True

    # Health
    resp_health = await client.get("/api/v1/system/health")
    assert resp_health.status_code == 200
    assert "components" in resp_health.json()

    # Data Quality
    resp_dq = await client.get("/api/v1/system/data-quality")
    assert resp_dq.status_code == 200
    assert "score" in resp_dq.json()

    # Provider Metrics
    resp_prov = await client.get("/api/v1/system/providers/metrics")
    assert resp_prov.status_code == 200
    assert "providers" in resp_prov.json()

    # Streaming Metrics
    resp_stream = await client.get("/api/v1/system/streaming/metrics")
    assert resp_stream.status_code == 200
    assert "events_ingested_total" in resp_stream.json()

    # Prometheus Metrics
    resp_prom = await client.get("/metrics")
    assert resp_prom.status_code == 200
    assert "railcast_events_total" in resp_prom.text
