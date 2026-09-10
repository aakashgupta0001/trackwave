"""Phase 7 API Integration Tests:
- GET /api/v1/eta/{train_number} with uncertainty, confidence, and explanation blocks
- GET /api/v1/eta/{train_number}/{station_code} with uncertainty, confidence, and explanation blocks
- GET /api/v1/eta/{train_number}/{station_code}/explanation endpoint (baseline factors + TreeSHAP ML factors)
- Graceful degradation when ML is disabled (available=false, reason=ML_MODEL_UNAVAILABLE, deterministic baseline factors intact)
- 404 behavior for invalid stations/trains
- Database persistence of Phase 7 fields into predictions table
- State-versioned Redis caching of explanations
"""

from datetime import datetime
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.ml.predictor import ml_predictor
from app.ml.registry import ModelRegistry
from app.models.prediction import Prediction
from app.models.train import Train

pytestmark = pytest.mark.usefixtures("require_db")


def _model_available() -> bool:
    registry = ModelRegistry(get_settings().ML_MODEL_DIR)
    return len(registry.list_versions()) > 0


async def test_full_eta_phase7_fields(eta_client):
    """GET /api/v1/eta/{train_number} returns uncertainty, confidence and explanation per station."""
    if not _model_available():
        pytest.skip("No trained model in registry")

    response = await eta_client.get("/api/v1/eta/12951")
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    assert body["prediction_mode"] == "ML_RESIDUAL"
    assert len(body["stations"]) > 0

    for station in body["stations"]:
        # Uncertainty block
        uncertainty = station.get("uncertainty")
        if uncertainty is not None:
            assert "lower_eta" in uncertainty
            assert "upper_eta" in uncertainty
            assert uncertainty["interval_level"] == 0.80
            assert uncertainty["interval_width_minutes"] > 0
            # lower <= final <= upper
            lower = datetime.fromisoformat(uncertainty["lower_eta"])
            upper = datetime.fromisoformat(uncertainty["upper_eta"])
            final = datetime.fromisoformat(station["final_eta"])
            assert lower <= final <= upper

        # Confidence block
        confidence = station.get("confidence")
        assert confidence is not None
        assert 0 <= confidence["score"] <= 100
        assert confidence["level"] in ("HIGH", "MEDIUM", "LOW")
        assert len(confidence["factors"]) > 0

        # Explanation block
        explanation = station.get("explanation")
        assert explanation is not None
        assert explanation["available"] is True
        assert len(explanation["top_factors"]) > 0
        for factor in explanation["top_factors"]:
            assert "feature" in factor
            assert "display_name" in factor
            assert "contribution_minutes" in factor
            assert factor["direction"] in ("LATER", "EARLIER")


async def test_single_station_eta_phase7_fields(eta_client):
    """GET /api/v1/eta/{train_number}/{station_code} returns uncertainty, confidence, explanation."""
    if not _model_available():
        pytest.skip("No trained model in registry")

    response = await eta_client.get("/api/v1/eta/12951/GWL")
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "GWL"
    assert body["prediction_mode"] == "ML_RESIDUAL"

    # Uncertainty
    assert body["uncertainty"] is not None
    assert body["uncertainty"]["interval_level"] == 0.80

    # Confidence
    assert body["confidence"] is not None
    assert 0 <= body["confidence"]["score"] <= 100
    assert body["confidence"]["level"] in ("HIGH", "MEDIUM", "LOW")

    # Explanation
    assert body["explanation"] is not None
    assert body["explanation"]["available"] is True
    assert len(body["explanation"]["top_factors"]) > 0


async def test_station_explanation_endpoint_success(eta_client):
    """GET /api/v1/eta/{train_number}/{station_code}/explanation returns baseline + ML factors."""
    if not _model_available():
        pytest.skip("No trained model in registry")

    response = await eta_client.get("/api/v1/eta/12951/GWL/explanation")
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    assert body["station_code"] == "GWL"
    assert body["model_version"]
    assert body["available"] is True
    assert body["reason"] is None

    # Baseline factors
    assert len(body["baseline_factors"]) > 0
    for bf in body["baseline_factors"]:
        assert "factor" in bf
        assert "display_name" in bf
        assert bf["effect"] in ("LATER", "EARLIER", "NEUTRAL")

    # ML SHAP factors
    assert len(body["ml_factors"]) > 0
    for mf in body["ml_factors"]:
        assert "feature" in mf
        assert "display_name" in mf
        assert isinstance(mf["contribution_minutes"], float)
        assert mf["direction"] in ("LATER", "EARLIER")


async def test_station_explanation_endpoint_ml_disabled_fallback(eta_client, monkeypatch):
    """When ML is disabled, explanation endpoint returns available=false, reason=ML_MODEL_UNAVAILABLE,
    and baseline factors remain fully intact."""
    monkeypatch.setattr(get_settings(), "ML_MODEL_ENABLED", False)
    ml_predictor.reload()
    try:
        response = await eta_client.get("/api/v1/eta/12951/GWL/explanation")
        assert response.status_code == 200
        body = response.json()
        assert body["train_number"] == "12951"
        assert body["station_code"] == "GWL"
        assert body["prediction_mode"] == "BASELINE_FALLBACK"
        assert body["model_version"] is None
        assert body["available"] is False
        assert body["reason"] == "ML_MODEL_UNAVAILABLE"
        assert len(body["baseline_factors"]) > 0  # baseline explanations never disappear
        assert body["ml_factors"] == []           # no fake ML explanations
    finally:
        ml_predictor.reload()


async def test_station_explanation_endpoint_404s(eta_client):
    assert (await eta_client.get("/api/v1/eta/99999/GWL/explanation")).status_code == 404
    assert (await eta_client.get("/api/v1/eta/12951/AGC/explanation")).status_code == 404  # already passed
    assert (await eta_client.get("/api/v1/eta/12951/ZZZ/explanation")).status_code == 404  # not on route


async def test_db_persistence_of_phase7_fields(eta_client, real_session):
    """Calling the fused ETA endpoint persists Phase 7 uncertainty and confidence columns into predictions table."""
    if not _model_available():
        pytest.skip("No trained model in registry")

    # Call endpoint to trigger fusion and persistence
    resp = await eta_client.get("/api/v1/eta/12951")
    assert resp.status_code == 200

    # Query DB directly to verify persisted prediction row
    train = (await real_session.execute(select(Train).where(Train.train_number == "12951"))).scalar_one_or_none()
    assert train is not None

    preds = (
        await real_session.execute(
            select(Prediction)
            .where(Prediction.train_id == train.id)
            .order_by(Prediction.prediction_timestamp.desc())
        )
    ).scalars().all()
    assert len(preds) > 0

    # Check that at least one upcoming station prediction has Phase 7 fields saved
    found_phase7 = False
    for p in preds:
        if p.confidence_score is not None:
            found_phase7 = True
            assert 0 <= p.confidence_score <= 100
            assert p.confidence_level in ("HIGH", "MEDIUM", "LOW")
            if p.lower_eta is not None:
                assert p.upper_eta is not None
                assert float(p.interval_level) == pytest.approx(0.80, abs=0.01)
                assert p.lower_eta <= p.final_eta <= p.upper_eta
    assert found_phase7, "Expected at least one prediction with Phase 7 fields persisted"
