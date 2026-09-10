"""Phase 5 API tests — the baseline ETA endpoints against the seeded sample network.

Requires PostgreSQL (skipped otherwise, like the other DB test modules). Uses the
Phase 2 seed data: e.g. train 12951 (Mumbai Rajdhani) whose latest seeded event sits
in the AGC-GWL section, and train 12002 (Bhopal Shatabdi) whose latest event is an
arrival at AGC.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.prediction import Prediction
from app.services import baseline_eta_service

pytestmark = pytest.mark.usefixtures("require_db")


async def test_baseline_eta_api_full_train(eta_client):
    response = await eta_client.get("/api/v1/eta/12951", params={"mode": "baseline"})
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    assert body["prediction_mode"] == "BASELINE"
    assert body["data_source"] == "SIMULATOR"
    assert body["data_status"] in {"SIMULATED", "STALE"}
    assert body["current_position"]["kind"] in {"IN_SECTION", "GPS_ONLY"}
    stations = body["stations"]
    codes = [s["station_code"] for s in stations]
    # Seeded latest event is inside AGC-GWL, so GWL..CSMT are upcoming, AGC is not.
    assert codes == ["GWL", "JHS", "BPL", "ET", "NGP", "CSMT"]
    assert "AGC" not in codes
    for s in stations:
        assert s["scheduled_arrival"] is not None
        assert s["baseline_eta"] is not None
        assert s["delay_minutes"] >= 0
        assert s["prediction_mode"] == "BASELINE"
        assert s["calculation_details"]["distance_source"] == "RAILWAY_SECTION"
    # Destination included, remaining distance grows monotonically.
    assert codes[-1] == "CSMT"
    dists = [s["remaining_distance_km"] for s in stations]
    assert dists == sorted(dists)
    assert body["calculation_details"]["recovery_model"] == "CONFIGURED_BASELINE_RECOVERY"


async def test_baseline_eta_api_single_station(eta_client):
    response = await eta_client.get("/api/v1/eta/12951/GWL", params={"mode": "baseline"})
    assert response.status_code == 200
    body = response.json()
    assert body["train_number"] == "12951"
    assert body["station_code"] == "GWL"
    assert body["station_name"] == "Gwalior"
    assert body["scheduled_arrival"] is not None
    assert body["baseline_eta"] is not None
    assert body["prediction_mode"] in {"BASELINE", "BASELINE_FALLBACK"}
    assert body["calculation_details"] is not None


async def test_baseline_eta_api_unknown_train(eta_client):
    response = await eta_client.get("/api/v1/eta/12001")
    assert response.status_code == 404


async def test_baseline_eta_api_unknown_station(eta_client):
    response = await eta_client.get("/api/v1/eta/12951/ZZZ")
    assert response.status_code == 404


async def test_baseline_eta_api_station_already_passed(eta_client):
    # 12951's seeded latest event is in AGC-GWL: AGC has been passed.
    response = await eta_client.get("/api/v1/eta/12951/AGC")
    assert response.status_code == 404
    assert "already passed" in response.json()["detail"] or "not an upcoming" in response.json()["detail"]


async def test_baseline_eta_api_station_at_current_location(eta_client):
    # 12002's seeded latest event is an arrival at AGC — AGC is the current location.
    response = await eta_client.get("/api/v1/eta/12002/AGC")
    assert response.status_code == 404


async def test_baseline_eta_api_upcoming_station_for_12002(eta_client):
    response = await eta_client.get("/api/v1/eta/12002/JHS")
    assert response.status_code == 200
    assert response.json()["station_code"] == "JHS"


async def test_scheduled_arrival_untouched_by_baseline(eta_client):
    """scheduled_arrival from the ETA API must equal the static timetable's clock time
    — the baseline engine estimates, it never rewrites the schedule. (Day offsets can
    shift the date, so the time-of-day is what's compared.)"""
    route_resp = await eta_client.get("/api/v1/trains/12951/route")
    assert route_resp.status_code == 200
    timetable = {r["station_code"]: r["arrival_time"] for r in route_resp.json()["route"]}
    eta_resp = await eta_client.get("/api/v1/eta/12951", params={"mode": "baseline"})
    for station in eta_resp.json()["stations"]:
        scheduled = station["scheduled_arrival"]
        assert scheduled is not None
        assert scheduled[11:19] == timetable[station["station_code"]]


async def test_predictions_persisted_on_fresh_computation(seeded_client, db_session):
    """A cache-bypassed engine run persists BASELINE Prediction rows — one current row
    per upcoming station (upsert-in-place), so repeated computations don't accumulate
    duplicates. ml_correction stays null (no ML in Phase 5)."""
    from sqlalchemy import select as sel

    from app.models.route import TrainRoute
    from app.models.train import Train

    train = (await db_session.execute(
        sel(Train).where(Train.train_number == "12951")
    )).scalar_one()
    route = (await db_session.execute(
        sel(TrainRoute).where(TrainRoute.train_id == train.id).order_by(TrainRoute.sequence_number)
    )).scalars().all()

    result1 = await baseline_eta_service.get_baseline_eta(db_session, "12951", use_cache=False)
    result2 = await baseline_eta_service.get_baseline_eta(db_session, "12951", use_cache=False)
    assert len(result1.stations) == len(route) - 3  # NDLS, MTJ passed; AGC passed (in AGC-GWL section)
    assert len(result2.stations) == len(result1.stations)

    rows = (await db_session.execute(
        sel(Prediction).where(
            Prediction.train_id == train.id,
            Prediction.prediction_mode == "BASELINE",
        )
    )).scalars().all()
    assert len(rows) == len(result1.stations)
    code_by_id = {entry.station_id: entry.station.station_code for entry in route}
    for station in result1.stations:
        matching = [r for r in rows if code_by_id[r.station_id] == station.station_code]
        assert len(matching) == 1
        row = matching[0]
        assert row.prediction_mode.value in {"BASELINE", "BASELINE_FALLBACK"}
        assert row.ml_correction_minutes is None
        assert row.model_version == "baseline-v1"
        assert row.baseline_eta is not None
        assert row.scheduled_eta is not None


async def test_eta_api_uses_cache_for_unchanged_state(eta_client):
    """With unchanged train state a second call is served from the Redis cache — the
    engine's pure computation is not re-run (its 'generated_at' is identical)."""
    from app.cache.redis import check_redis_connection

    if not await check_redis_connection():
        pytest.skip("Redis is not reachable — the cache-hit behaviour can't be verified.")
    first = (await eta_client.get("/api/v1/eta/12951", params={"mode": "baseline"})).json()
    second = (await eta_client.get("/api/v1/eta/12951", params={"mode": "baseline"})).json()
    assert first["generated_at"] == second["generated_at"]
    assert first["stations"] == second["stations"]
