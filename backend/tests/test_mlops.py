"""Tests for Phase 10 MLOps model lifecycle, quality gates, promotion, rollback, and admin security."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.security import audit_logger, verify_admin_key
from app.ml.registry import model_registry


def test_model_registry_catalog():
    models = model_registry.list_models()
    assert len(models) >= 1
    active_ver = model_registry.active_version()
    assert active_ver is not None
    assert any(m["model_version"] == active_ver for m in models)


def test_quality_gate_validation():
    active_ver = model_registry.active_version()

    # Non-existent version fails
    passed, reason, _ = model_registry.validate_candidate("non-existent-version-xyz")
    assert passed is False

    # Existing active version validates against baseline
    passed, reason, details = model_registry.validate_candidate(active_ver)
    assert passed is True
    assert details["candidate_version"] == active_ver


def test_model_promotion_and_rollback():
    active_initial = model_registry.active_version()

    # Simulate promoting active_initial with force=True
    success, msg = model_registry.promote_model(active_initial, actor="test_runner", force=True)
    assert success is True
    assert model_registry.active_version() == active_initial

    # Test audit logger recording
    entry = audit_logger.record_event(
        action="TEST_ACTION",
        actor="test_user",
        previous_value="v1",
        new_value="v2",
        reason="Unit testing",
    )
    assert entry.action == "TEST_ACTION"
    recent = audit_logger.get_entries(limit=5)
    assert any(e.action == "TEST_ACTION" for e in recent)


def test_admin_api_key_security():
    from fastapi import HTTPException
    from app.core.config import get_settings

    settings = get_settings()

    # With key configured
    with patch.object(settings, "ADMIN_API_KEY", "secret-token-123"):
        with patch.object(settings, "ENVIRONMENT", "production"):
            # Missing header -> 401
            with pytest.raises(HTTPException) as exc1:
                verify_admin_key(x_admin_api_key=None)
            assert exc1.value.status_code == 401

            # Invalid header -> 401
            with pytest.raises(HTTPException) as exc2:
                verify_admin_key(x_admin_api_key="wrong-token")
            assert exc2.value.status_code == 401

            # Correct header -> passes
            user = verify_admin_key(x_admin_api_key="secret-token-123")
            assert user == "admin-user"


@pytest.mark.asyncio
async def test_mlops_api_endpoints(client: AsyncClient):
    # Models catalog
    resp_models = await client.get("/api/v1/system/models")
    assert resp_models.status_code == 200
    data = resp_models.json()
    assert "active_model" in data
    assert len(data["models"]) >= 1

    # Model metrics
    active_ver = data["active_model"]
    resp_metrics = await client.get(f"/api/v1/system/models/{active_ver}/metrics")
    assert resp_metrics.status_code == 200
    m_data = resp_metrics.json()
    assert m_data["model_version"] == active_ver
    assert "uncertainty_coverage_percent" in m_data

    # Audit log
    resp_audit = await client.get("/api/v1/system/audit-log")
    assert resp_audit.status_code == 200
    assert isinstance(resp_audit.json(), list)
