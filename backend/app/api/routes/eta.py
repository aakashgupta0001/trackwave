"""ETA API (Phases 5 + 6).

`mode=final` (default) applies the Phase 6 residual fusion:
    FINAL ETA = BASELINE ETA + ML PREDICTED RESIDUAL (clamped)
with `prediction_mode=ML_RESIDUAL` and the model `model_version` set. When the ML layer
is unavailable for any reason the response degrades cleanly:
    prediction_mode=BASELINE_FALLBACK, model_version=null, final_eta=baseline_eta.

`mode=baseline` returns the pure Phase 5 deterministic baseline (no ML anywhere) —
useful for comparison and for ML-free deployments.

`mode` semantics per response: `scheduled_arrival` is the untouched timetable value;
`baseline_eta` the Phase 5 estimate; `predicted_residual_minutes` the clamped ML
correction (with `predicted_residual_raw` + `residual_clipped` provenance); `final_eta`
the fused estimate. One value is never overwritten with another.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.eta import BaselineEtaResponse, FullExplanationResponse, SingleStationEtaResponse
from app.services import baseline_eta_service, eta_fusion_service
from app.services.exceptions import NotFoundError

router = APIRouter(tags=["eta"])


@router.get(
    "/eta/{train_number}",
    response_model=BaselineEtaResponse,
    summary="ETA for every upcoming station of a train (baseline + optional ML residual)",
    description=(
        "Phase 5 deterministic section-aware BASELINE ETA for each remaining station "
        "(expected-speed hierarchy, scheduled halts, delay propagation with conservative "
        "recovery), plus — by default (mode=final) — the Phase 6 ML residual fusion: "
        "final_eta = baseline_eta + predicted_residual_minutes (clamped to configured "
        "safety bounds; clipping is reported per station). "
        "Phase 7 uncertainty intervals, confidence scores and explanations are included. "
        "If no trained model is available or ML fails, the response falls back cleanly: "
        "prediction_mode=BASELINE_FALLBACK, model_version=null, final_eta=baseline_eta. "
        "Use mode=baseline for the pure deterministic estimate. "
        "`scheduled_arrival` is never modified. Results are cached against the train's "
        "latest event timestamp, so a changed state always yields a fresh calculation."
    ),
)
async def get_train_eta(
    train_number: str,
    mode: str = Query(default="final", pattern="^(final|baseline)$", description="final = baseline + ML residual (falls back to baseline); baseline = deterministic only"),
    include_explanation: bool = Query(default=True, description="Include Phase 7 top SHAP explanation factors"),
    journey_date: date | None = Query(
        default=None, description="Origin departure date anchoring the timetable (defaults to today)"
    ),
    session: AsyncSession = Depends(get_db),
) -> BaselineEtaResponse:
    try:
        if mode == "baseline":
            return await baseline_eta_service.get_baseline_eta(session, train_number, journey_date)
        return await eta_fusion_service.get_final_eta(
            session, train_number, journey_date, include_explanations=include_explanation
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/eta/{train_number}/{station_code}",
    response_model=SingleStationEtaResponse,
    summary="ETA for one specific upcoming station (baseline + optional ML residual)",
    description=(
        "Same calculation as the full-train endpoint, narrowed to a single upcoming "
        "station: scheduled arrival, baseline ETA, predicted residual (clamped), final "
        "ETA, uncertainty interval, confidence score and explanation factors. "
        "404 if the train doesn't exist, the station isn't on the route, or the station "
        "has already been passed (or is the current location)."
    ),
)
async def get_train_station_eta(
    train_number: str,
    station_code: str,
    mode: str = Query(default="final", pattern="^(final|baseline)$"),
    include_explanation: bool = Query(default=True, description="Include Phase 7 top SHAP explanation factors"),
    journey_date: date | None = Query(
        default=None, description="Origin departure date anchoring the timetable (defaults to today)"
    ),
    session: AsyncSession = Depends(get_db),
) -> SingleStationEtaResponse:
    try:
        if mode == "baseline":
            return await baseline_eta_service.get_station_eta(session, train_number, station_code, journey_date)
        return await eta_fusion_service.get_station_final_eta(
            session, train_number, station_code, journey_date, include_explanations=include_explanation
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/eta/{train_number}/{station_code}/explanation",
    response_model=FullExplanationResponse,
    summary="Detailed explainability for a station prediction (baseline factors + ML TreeSHAP)",
    description=(
        "Returns the deterministic baseline arithmetic factors (current delay, expected running "
        "time, delay recovery) and — when an ML model is active — exact TreeSHAP feature contributions "
        "sorted by absolute impact with human-readable display names and direction (LATER/EARLIER). "
        "If no ML model is available or SHAP computation fails, returns available=false with an "
        "explicit reason — never fabricates explanations."
    ),
)
async def get_train_station_explanation(
    train_number: str,
    station_code: str,
    journey_date: date | None = Query(
        default=None, description="Origin departure date anchoring the timetable (defaults to today)"
    ),
    session: AsyncSession = Depends(get_db),
) -> FullExplanationResponse:
    try:
        return await eta_fusion_service.get_station_explanation(session, train_number, station_code, journey_date)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
