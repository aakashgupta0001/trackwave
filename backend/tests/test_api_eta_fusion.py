from datetime import datetime

"""Phase 6 fusion API tests — FINAL ETA = BASELINE ETA + ML RESIDUAL.

Case A: a trained model is registered (skipped if the registry is empty on this
machine) → responses carry ML_RESIDUAL mode, model_version, clamped residuals.
Case B: ML disabled by configuration → BASELINE_FALLBACK with final_eta = baseline_eta.
"""

import pytest

from app.core.config import get_settings
from app.ml.predictor import ml_predictor
from app.ml.registry import ModelRegistry

pytestmark = pytest.mark.usefixtures("require_db")


def _model_available() -> bool:
    registry = ModelRegistry(get_settings().ML_MODEL_DIR)
    return len(registry.list_versions()) > 0


async def test_final_eta_endpoint_with_model(eta_client):
    """Case A: with a trained model, the default mode fuses residual into final ETA."""
    if not _model_available():
        pytest.skip("No trained model in the registry — train one with `python -m scripts.train_eta_model`")
    response = await eta_client.get("/api/v1/eta/12951")
    assert response.status_code == 200
    body = response.json()
    assert body["prediction_mode"] == "ML_RESIDUAL"
    assert body["model_version"]
    assert body["calculation_details"]["ml_fusion"]["residual_clamp_minutes"] == [
        get_settings().ML_RESIDUAL_MINUTES_MIN, get_settings().ML_RESIDUAL_MINUTES_MAX,
    ]
    for station in body["stations"]:
        assert station["baseline_eta"] is not None
        assert station["final_eta"] is not None
        assert station["scheduled_arrival"] is not None
        # The three ETA concepts never overwrite each other.
        assert station["scheduled_arrival"] != station["baseline_eta"] or station["delay_minutes"] == 0
        raw = station["predicted_residual_raw"]
        used = station["predicted_residual_minutes"]
        assert raw is not None and used is not None
        # Clamping respected.
        assert get_settings().ML_RESIDUAL_MINUTES_MIN <= used <= get_settings().ML_RESIDUAL_MINUTES_MAX
        assert station["residual_clipped"] == (raw != used)
        # final = baseline + used residual (to the second).
        delta = (station["final_eta"] and station["baseline_eta"]) and (
            datetime.fromisoformat(station["final_eta"])
            - datetime.fromisoformat(station["baseline_eta"])
        ).total_seconds() / 60.0
        assert abs(delta - used) < 0.05


async def test_final_eta_endpoint_disabled_falls_back_to_baseline(eta_client, monkeypatch):
    """Case B (mandatory): no ML at all → still a valid baseline ETA response."""
    monkeypatch.setattr(get_settings(), "ML_MODEL_ENABLED", False)
    ml_predictor.reload()
    try:
        response = await eta_client.get("/api/v1/eta/12951")
        assert response.status_code == 200
        body = response.json()
        assert body["prediction_mode"] == "BASELINE_FALLBACK"
        assert body["model_version"] is None
        for station in body["stations"]:
            assert station["predicted_residual_minutes"] is None
            assert station["final_eta"] == station["baseline_eta"]
            assert station["final_delay_minutes"] == station["delay_minutes"]
    finally:
        ml_predictor.reload()


async def test_single_station_final_eta(eta_client):
    if not _model_available():
        pytest.skip("No trained model in the registry")
    response = await eta_client.get("/api/v1/eta/12951/GWL")
    assert response.status_code == 200
    body = response.json()
    assert body["station_code"] == "GWL"
    assert body["prediction_mode"] == "ML_RESIDUAL"
    assert body["model_version"]
    assert body["scheduled_arrival"] is not None
    assert body["baseline_eta"] is not None
    assert body["final_eta"] is not None
    assert body["predicted_residual_minutes"] is not None
    assert body["final_delay_minutes"] >= 0


async def test_single_station_final_eta_fallback(eta_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ML_MODEL_ENABLED", False)
    ml_predictor.reload()
    try:
        response = await eta_client.get("/api/v1/eta/12951/GWL")
        assert response.status_code == 200
        body = response.json()
        assert body["prediction_mode"] == "BASELINE_FALLBACK"
        assert body["model_version"] is None
        assert body["final_eta"] == body["baseline_eta"]
    finally:
        ml_predictor.reload()


async def test_final_eta_still_404s_correctly(eta_client):
    assert (await eta_client.get("/api/v1/eta/12001")).status_code == 404
    assert (await eta_client.get("/api/v1/eta/12951/AGC")).status_code == 404  # passed
    assert (await eta_client.get("/api/v1/eta/12951/ZZZ")).status_code == 404
