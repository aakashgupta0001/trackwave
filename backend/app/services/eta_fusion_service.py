"""ETA Fusion service (Phase 6): FINAL ETA = BASELINE ETA + ML PREDICTED RESIDUAL.

Real-time inference only — never trains at request time. For every upcoming station:

    1. baseline ETA            (Phase 5 engine, unchanged)
    2. features                (app/ml/features — same builder as training)
    3. residual                (XGBoost predictor; clamped to configured safety bounds)
    4. final_eta               (baseline + clamped residual)

Any ML failure — model disabled, missing, unloadable, feature problems, runtime
errors — degrades to FINAL ETA = BASELINE ETA with prediction_mode=BASELINE_FALLBACK.
The ML layer is a correction, never a single point of failure.

Results are cached in Redis under a state-aware key
`railcast:eta:{train}:{state_timestamp}:{model_version}` so a changed train state can
never be served an old fusion result.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import redis_client
from app.core.config import get_settings
from app.ml import fallback as ml_fallback
from app.ml.explain import safe_explain
from app.ml.features import FeatureContext, build_feature_row, encode_row, row_to_vector, vector_is_finite_enough
from app.ml.predictor import ml_predictor
from app.ml.uncertainty import prediction_interval
from app.models.enums import PredictionMode
from app.schemas.eta import (
    BaselineEtaResponse,
    BaselineFactorOut,
    ConfidenceOut,
    ConfidenceFactorOut,
    EtaStation,
    ExplanationOut,
    ExplanationFactorOut,
    FullExplanationResponse,
    SingleStationEtaResponse,
    UncertaintyInterval,
)
from app.services import baseline_eta_service, confidence_service
from app.services.baseline_explain import baseline_factors
from app.services.position_resolver import dedupe_route

logger = logging.getLogger(__name__)


def _clamp_residual(raw: float) -> tuple[float, bool]:
    """Configurable safety clamp (RAILCAST model configuration, not railway policy):
    a +240-minute residual is clipped, and the clipping is recorded, never hidden."""
    s = get_settings()
    used = max(s.ML_RESIDUAL_MINUTES_MIN, min(s.ML_RESIDUAL_MINUTES_MAX, raw))
    return round(used, 2), used != round(raw, 2)


def _build_feature_contexts(
    session: AsyncSession,
    train,
    route,
    latest_event,
    recent_events,
    baseline: BaselineEtaResponse,
):
    """One FeatureContext per upcoming station, all as of the baseline's generation
    time (the prediction timestamp). Reuses the exact Phase 5 engine outputs so the
    feature distribution matches training."""
    from app.services.position_resolver import dedupe_route as _dedupe

    route = _dedupe(route)
    first_idx = baseline.calculation_details.get("_first_upcoming_index")
    contexts: list[tuple[EtaStation, FeatureContext, int]] = []
    total_distance = baseline.remaining_distance_km or 0.0
    prediction_time = baseline.generated_at

    recent = [e for e in recent_events if e.timestamp <= prediction_time]

    n = len(baseline.stations)
    for offset, station in enumerate(baseline.stations):
        station_index = (first_idx + offset) if first_idx is not None else None
        if station_index is None or station_index >= len(route):
            continue
        details = station.calculation_details
        contexts.append(
            (
                station,
                FeatureContext(
                    train=train,
                    latest_event=latest_event,
                    route=route,
                    station_index=station_index,
                    prediction_time=prediction_time,
                    baseline_delay_minutes=station.delay_minutes,
                    baseline_minutes_ahead=(
                        (station.baseline_eta - prediction_time).total_seconds() / 60.0
                        if station.baseline_eta is not None
                        else float("nan")
                    ),
                    remaining_distance_km=station.remaining_distance_km,
                    remaining_sections=n - offset,
                    remaining_stations=n - offset,
                    route_progress_percent=(
                        100.0 * (1.0 - station.remaining_distance_km / total_distance)
                        if total_distance > 0
                        else float("nan")
                    ),
                    recent_events=list(recent),
                ),
                station_index,
            )
        )
    return contexts


def _first_upcoming_index(route, baseline: BaselineEtaResponse) -> int | None:
    """Recover the route index of the first upcoming station by matching the response's
    first station against the deduplicated route."""
    if not baseline.stations:
        return None
    route = dedupe_route(route)
    first_code = baseline.stations[0].station_code
    return next((i for i, e in enumerate(route) if e.station.station_code == first_code), None)



def _station_uncertainty(loaded_model, station, generated_at) -> UncertaintyInterval | None:
    """Interval for one station from the ACTIVE model's uncertainty metadata (stored in
    the artifact, so version compatibility is structural). None → reported unavailable."""
    if loaded_model is None or station.final_eta is None:
        return None
    interval = prediction_interval(
        loaded_model.metadata.get("uncertainty"),
        station.final_eta,
        _horizon_for(station, generated_at),
    )
    if not interval.available or interval.lower_eta is None or interval.upper_eta is None:
        return None
    return UncertaintyInterval(
        lower_eta=interval.lower_eta,
        upper_eta=interval.upper_eta,
        interval_level=interval.interval_level or 0.80,
        interval_width_minutes=interval.interval_width_minutes or 0.0,
        source=interval.source,
    )


def _horizon_for(station, generated_at) -> float | None:
    """Prediction horizon in minutes: baseline ETA minus the prediction's generation
    time. None when no baseline ETA exists."""
    if station.baseline_eta is None or generated_at is None:
        return None
    return (station.baseline_eta - generated_at).total_seconds() / 60.0


def _station_confidence(baseline, station, ctx, loaded_model, generated_at) -> ConfidenceOut:
    """Transparent additive confidence score (NOT a probability of on-time arrival)."""
    from datetime import datetime, timezone

    latest = ctx.latest_event
    event_age = (
        (datetime.now(timezone.utc) - latest.timestamp).total_seconds()
        if latest is not None and latest.timestamp is not None
        else None
    )
    details = station.calculation_details
    section_known = bool(details and details.distance_source in ("RAILWAY_SECTION", "ROUTE_DISTANCE_METADATA"))
    position_known = baseline.current_position.kind in ("AT_STATION", "DEPARTED_STATION", "IN_SECTION", "GPS_ONLY")
    dataset_rows = int(loaded_model.metadata.get("dataset_rows")) if loaded_model is not None else None
    result = confidence_service.compute_confidence(
        data_status=baseline.data_status.value if hasattr(baseline.data_status, "value") else str(baseline.data_status),
        event_age_seconds=event_age,
        position_known=position_known,
        section_known=section_known,
        model_available=loaded_model is not None,
        dataset_rows=dataset_rows,
        baseline_minutes_ahead=_horizon_for(station, generated_at),
    )
    return ConfidenceOut(
        score=result.score,
        level=result.level,
        factors=[ConfidenceFactorOut(factor=f.factor, impact=f.impact) for f in result.factors],
    )


async def get_final_eta(
    session: AsyncSession,
    train_number: str,
    journey_date: date | None = None,
    *,
    use_cache: bool = True,
    include_explanations: bool = True,
) -> BaselineEtaResponse:
    """Baseline + clamped ML residual for every upcoming station. Falls back to the
    baseline (mode BASELINE_FALLBACK, final = baseline) whenever ML is unusable."""
    baseline = await baseline_eta_service.get_baseline_eta(session, train_number, journey_date)

    train, route, latest_event = await baseline_eta_service.load_engine_inputs(session, train_number)
    recent_events = await _load_recent_events(session, train.id)

    model_version: str | None = None
    loaded_model = None
    any_fallback_reason = None
    if ml_predictor.is_available():
        try:
            loaded_model = ml_predictor._ensure_loaded()
            model_version = loaded_model.version
        except Exception:  # noqa: BLE001 — covered by the per-station fallback below
            model_version = None

    cache_key = None
    settings = get_settings()
    if use_cache and model_version:
        state_token = latest_event.timestamp.isoformat() if latest_event is not None else "no-event"
        cache_key = f"railcast:eta:{train.train_number}:{state_token}:{model_version}"
        cached = await _read_cache(cache_key)
        if cached is not None:
            try:
                return BaselineEtaResponse.model_validate(cached)
            except Exception:
                logger.warning("Discarding unreadable fused ETA cache entry key=%s", cache_key)

    # Recover the first upcoming index BEFORE any mutation, then fuse per station.
    baseline.calculation_details["_first_upcoming_index"] = _first_upcoming_index(route, baseline)
    contexts = _build_feature_contexts(session, train, route, latest_event, recent_events, baseline)

    any_ml = False
    any_fallback_reason = None
    fused_stations: list[EtaStation] = []
    for station, ctx, _idx in contexts:
        raw_row = build_feature_row(ctx)
        encoded = encode_row(raw_row, loaded_model.encoder) if loaded_model is not None else None
        if model_version is not None and encoded is not None and vector_is_finite_enough(encoded):
            outcome = ml_fallback.safe_predict(
                lambda c=ctx: ml_predictor.predict(c).raw_residual_minutes, model_version
            )
        else:
            outcome = ml_fallback.FallbackOutcome(None, None, ml_fallback.REASON_NO_MODEL if model_version is None else ml_fallback.REASON_FEATURES)

        station = station.model_copy()
        if outcome.used_ml:
            raw_residual = round(outcome.residual_minutes, 2)
            used_residual, clipped = _clamp_residual(raw_residual)
            final_eta = (
                station.baseline_eta + timedelta(minutes=used_residual)
                if station.baseline_eta is not None
                else None
            )
            final_delay = (
                round(max(0.0, (final_eta - station.scheduled_arrival).total_seconds() / 60.0), 2)
                if final_eta is not None and station.scheduled_arrival is not None
                else None
            )
            station = station.model_copy(
                update={
                    "prediction_mode": PredictionMode.ML_RESIDUAL,
                    "predicted_residual_minutes": used_residual,
                    "predicted_residual_raw": raw_residual,
                    "residual_clipped": clipped,
                    "final_eta": final_eta,
                    "final_delay_minutes": final_delay,
                }
            )
            any_ml = True
        else:
            any_fallback_reason = outcome.reason
            station = station.model_copy(
                update={
                    "prediction_mode": PredictionMode.BASELINE_FALLBACK,
                    "predicted_residual_minutes": None,
                    "predicted_residual_raw": None,
                    "residual_clipped": False,
                    "final_eta": station.baseline_eta,
                    "final_delay_minutes": station.delay_minutes,
                }
            )
        # --- Phase 7: uncertainty, confidence, explanation -------------------------
        station = station.model_copy(
            update={
                "uncertainty": _station_uncertainty(loaded_model, station, baseline.generated_at),
                "confidence": _station_confidence(baseline, station, ctx, loaded_model, baseline.generated_at),
            }
        )
        if include_explanations:
            vector = row_to_vector(encoded) if encoded is not None else None
            factors, reason = (
                safe_explain(loaded_model, vector)
                if (loaded_model is not None and vector is not None)
                else (None, "ML_MODEL_UNAVAILABLE" if loaded_model is None else "EXPLANATION_UNAVAILABLE")
            )
            station = station.model_copy(
                update={
                    "explanation": ExplanationOut(
                        available=factors is not None,
                        reason=reason,
                        top_factors=[ExplanationFactorOut(**f.as_dict()) for f in (factors or [])],
                    )
                }
            )
        fused_stations.append(station)

    # Stations the feature builder skipped (e.g. route mismatch) keep baseline-final.
    if len(fused_stations) < len(baseline.stations):
        fused_codes = {st.station_code for st in fused_stations}
        for station in baseline.stations:
            if station.station_code not in fused_codes:
                fused_stations.append(
                    station.model_copy(
                        update={
                            "prediction_mode": PredictionMode.BASELINE_FALLBACK,
                            "final_eta": station.baseline_eta,
                            "final_delay_minutes": station.delay_minutes,
                        }
                    )
                )
        fused_stations.sort(key=lambda st: st.sequence_number)

    response = baseline.model_copy(
        update={
            "prediction_mode": PredictionMode.ML_RESIDUAL if any_ml else PredictionMode.BASELINE_FALLBACK,
            "model_version": model_version if any_ml else None,
            "stations": fused_stations,
            "calculation_details": {
                **baseline.calculation_details,
                "ml_fusion": {
                    "model_version": model_version,
                    "residual_clamp_minutes": [settings.ML_RESIDUAL_MINUTES_MIN, settings.ML_RESIDUAL_MINUTES_MAX],
                    "fallback_reason": any_fallback_reason,
                    "residual_clipping_applied": any(st.residual_clipped for st in fused_stations),
                },
            },
        }
    )
    response.calculation_details.pop("_first_upcoming_index", None)

    if cache_key:
        await _write_cache(cache_key, response.model_dump(mode="json"))
    await _persist_fused_predictions(session, train, response)
    return response


async def _load_recent_events(session: AsyncSession, train_id: int):
    from app.repositories import event_repository

    try:
        return await event_repository.get_recent_for_train(session, train_id, limit=2)
    except Exception:  # noqa: BLE001 — trend feature is optional
        return []


async def get_station_final_eta(
    session: AsyncSession,
    train_number: str,
    station_code: str,
    journey_date: date | None = None,
    *,
    include_explanations: bool = True,
) -> SingleStationEtaResponse:
    """Final (fused) ETA for one specific upcoming station."""
    code = station_code.upper()
    response = await get_final_eta(session, train_number, journey_date, include_explanations=include_explanations)
    match = next((st for st in response.stations if st.station_code == code), None)
    if match is None:
        from app.repositories import station_repository
        from app.services.exceptions import NotFoundError

        station = await station_repository.get_by_code(session, code)
        if station is None:
            raise NotFoundError(f"Station {code} not found")
        raise NotFoundError(
            f"Station {code} is not an upcoming stop for train {train_number} "
            "(already passed, at destination, or not on the route)"
        )
    return SingleStationEtaResponse(
        train_number=response.train_number,
        station_code=match.station_code,
        station_name=match.station_name,
        scheduled_arrival=match.scheduled_arrival,
        baseline_eta=match.baseline_eta,
        delay_minutes=match.delay_minutes,
        predicted_residual_minutes=match.predicted_residual_minutes,
        predicted_residual_raw=match.predicted_residual_raw,
        residual_clipped=match.residual_clipped,
        final_eta=match.final_eta,
        final_delay_minutes=match.final_delay_minutes,
        remaining_distance_km=match.remaining_distance_km,
        prediction_mode=response.prediction_mode,
        model_version=response.model_version,
        data_source=response.data_source,
        data_status=response.data_status,
        calculation_details=match.calculation_details,
        uncertainty=match.uncertainty,
        confidence=match.confidence,
        explanation=match.explanation,
    )


async def get_station_explanation(
    session: AsyncSession,
    train_number: str,
    station_code: str,
    journey_date: date | None = None,
    *,
    use_cache: bool = True,
) -> FullExplanationResponse:
    """Full explanation for one station: deterministic baseline factors + exact TreeSHAP
    factors from the active ML residual model. When no model is available, available=False
    and reason='ML_MODEL_UNAVAILABLE'; if SHAP fails, reason='EXPLANATION_UNAVAILABLE'.
    Never fabricates explanation values."""
    code = station_code.upper()
    baseline = await baseline_eta_service.get_baseline_eta(session, train_number, journey_date)
    match = next((st for st in baseline.stations if st.station_code == code), None)
    if match is None:
        from app.repositories import station_repository
        from app.services.exceptions import NotFoundError

        station = await station_repository.get_by_code(session, code)
        if station is None:
            raise NotFoundError(f"Station {code} not found")
        raise NotFoundError(
            f"Station {code} is not an upcoming stop for train {train_number} "
            "(already passed, at destination, or not on the route)"
        )

    # 1. Baseline factors from baseline calculation details
    b_factors = [BaselineFactorOut(**bf.as_dict()) for bf in baseline_factors(match.calculation_details)]

    # 2. Check model availability
    loaded_model = None
    model_version = None
    if ml_predictor.is_available():
        try:
            loaded_model = ml_predictor._ensure_loaded()
            model_version = loaded_model.version
        except Exception:
            loaded_model = None
            model_version = None

    train, route, latest_event = await baseline_eta_service.load_engine_inputs(session, train_number)
    state_token = latest_event.timestamp.isoformat() if latest_event is not None else "no-event"

    # 3. Check Redis cache if model is available
    settings = get_settings()
    cache_key = None
    if use_cache and model_version:
        cache_key = f"railcast:explanation:{train.train_number}:{code}:{state_token}:{model_version}"
        cached = await _read_cache(cache_key)
        if cached is not None:
            try:
                return FullExplanationResponse.model_validate(cached)
            except Exception:
                logger.warning("Discarding unreadable explanation cache entry key=%s", cache_key)

    # If no model is available -> clean fallback
    if loaded_model is None or model_version is None:
        return FullExplanationResponse(
            train_number=train.train_number,
            station_code=code,
            prediction_mode=PredictionMode.BASELINE_FALLBACK,
            model_version=None,
            prediction_timestamp=baseline.generated_at,
            final_eta=match.baseline_eta,
            predicted_residual_minutes=None,
            available=False,
            reason="ML_MODEL_UNAVAILABLE",
            baseline_factors=b_factors,
            ml_factors=[],
        )

    # 4. Compute ML residual prediction & TreeSHAP explanation for this station
    recent_events = await _load_recent_events(session, train.id)
    baseline.calculation_details["_first_upcoming_index"] = _first_upcoming_index(route, baseline)
    contexts = _build_feature_contexts(session, train, route, latest_event, recent_events, baseline)
    target_ctx = next((ctx for st, ctx, _ in contexts if st.station_code == code), None)

    if target_ctx is None:
        return FullExplanationResponse(
            train_number=train.train_number,
            station_code=code,
            prediction_mode=PredictionMode.BASELINE_FALLBACK,
            model_version=model_version,
            prediction_timestamp=baseline.generated_at,
            final_eta=match.baseline_eta,
            predicted_residual_minutes=None,
            available=False,
            reason="EXPLANATION_UNAVAILABLE",
            baseline_factors=b_factors,
            ml_factors=[],
        )

    raw_row = build_feature_row(target_ctx)
    encoded = encode_row(raw_row, loaded_model.encoder)
    vector = row_to_vector(encoded) if (encoded is not None and vector_is_finite_enough(encoded)) else None

    if vector is None:
        return FullExplanationResponse(
            train_number=train.train_number,
            station_code=code,
            prediction_mode=PredictionMode.BASELINE_FALLBACK,
            model_version=model_version,
            prediction_timestamp=baseline.generated_at,
            final_eta=match.baseline_eta,
            predicted_residual_minutes=None,
            available=False,
            reason="EXPLANATION_UNAVAILABLE",
            baseline_factors=b_factors,
            ml_factors=[],
        )

    outcome = ml_fallback.safe_predict(
        lambda: ml_predictor.predict(target_ctx).raw_residual_minutes, model_version
    )
    predicted_residual = None
    final_eta = match.baseline_eta
    prediction_mode = PredictionMode.BASELINE_FALLBACK
    if outcome.used_ml:
        predicted_residual, _ = _clamp_residual(round(outcome.residual_minutes, 2))
        final_eta = match.baseline_eta + timedelta(minutes=predicted_residual) if match.baseline_eta else None
        prediction_mode = PredictionMode.ML_RESIDUAL

    factors, reason = safe_explain(loaded_model, vector)
    ml_factors = [ExplanationFactorOut(**f.as_dict()) for f in (factors or [])]

    response = FullExplanationResponse(
        train_number=train.train_number,
        station_code=code,
        prediction_mode=prediction_mode,
        model_version=model_version,
        prediction_timestamp=baseline.generated_at,
        final_eta=final_eta,
        predicted_residual_minutes=predicted_residual,
        available=factors is not None,
        reason=reason,
        baseline_factors=b_factors,
        ml_factors=ml_factors,
    )

    if cache_key and response.available:
        try:
            await redis_client.set(
                cache_key,
                json.dumps(response.model_dump(mode="json"), default=str),
                ex=settings.EXPLANATION_CACHE_TTL_SECONDS,
            )
        except Exception:
            logger.warning("Redis unavailable writing explanation cache key=%s", cache_key, exc_info=True)

    return response


async def _read_cache(key: str) -> dict | None:
    try:
        raw = await redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("Redis unavailable reading fused ETA cache key=%s", key, exc_info=True)
        return None


async def _write_cache(key: str, payload: dict) -> None:
    try:
        await redis_client.set(key, json.dumps(payload, default=str), ex=get_settings().ML_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis unavailable writing fused ETA cache key=%s", key, exc_info=True)


async def _persist_fused_predictions(session: AsyncSession, train, response: BaselineEtaResponse) -> None:
    """Best-effort persistence of fused predictions: ML_RESIDUAL rows carry the applied
    (clamped) correction and final ETA; BASELINE_FALLBACK rows carry final = baseline."""
    from app.repositories import prediction_repository

    try:
        for station in response.stations:
            mode = station.prediction_mode if station.prediction_mode != PredictionMode.BASELINE else PredictionMode.BASELINE_FALLBACK
            await prediction_repository.upsert_baseline(
                session,
                train_id=train.id,
                station_code=station.station_code,
                prediction_timestamp=response.generated_at,
                scheduled_eta=station.scheduled_arrival,
                baseline_eta=station.baseline_eta,
                prediction_mode=mode,
                model_version=response.model_version,
                ml_correction_minutes=station.predicted_residual_minutes,
                final_eta=station.final_eta,
                lower_eta=station.uncertainty.lower_eta if station.uncertainty else None,
                upper_eta=station.uncertainty.upper_eta if station.uncertainty else None,
                interval_level=station.uncertainty.interval_level if station.uncertainty else None,
                confidence_score=station.confidence.score if station.confidence else None,
                confidence_level=station.confidence.level if station.confidence else None,
            )
        await session.commit()
    except Exception:
        logger.warning("Failed to persist fused predictions for train %s", train.train_number, exc_info=True)
        await session.rollback()
