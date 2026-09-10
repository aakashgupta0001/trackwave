"""System monitoring, observability, health probes, and MLOps management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import audit_logger, verify_admin_key
from app.db.session import get_db
from app.ml.registry import model_registry
from app.monitoring.data_quality import data_quality_tracker
from app.monitoring.drift import check_drift
from app.monitoring.health import check_liveness, check_readiness, check_system_health
from app.monitoring.metrics import generate_prometheus_metrics, get_system_metrics
from app.monitoring.model_quality import evaluate_model_performance
from app.monitoring.schemas import (
    AuditLogEntry,
    DataQualityResponse,
    DriftAnalysisResponse,
    LivenessResponse,
    ModelCatalogResponse,
    ModelEvaluationResponse,
    ModelMetadataResponse,
    ProviderMetricsResponse,
    ReadinessResponse,
    StreamingMetricsResponse,
    SystemHealthResponse,
)
from app.repositories import alert_repository
from app.schemas.alert import AlertRead
from app.streaming.metrics import streaming_metrics
from app.streaming.websocket import ws_manager

router = APIRouter(prefix="/system", tags=["system"])


class RollbackRequest(BaseModel):
    target_version: str
    reason: str | None = None


# --- 1. Health, Readiness, and Liveness Probes --------------------------------

@router.get(
    "/health",
    response_model=SystemHealthResponse,
    summary="Comprehensive system health check across all platform components",
)
async def get_system_health_endpoint() -> SystemHealthResponse:
    """Evaluates connectivity and operational state of Database, Redis, Streaming, ML, Provider, and Network."""
    return await check_system_health()


@router.get(
    "/readiness",
    response_model=ReadinessResponse,
    summary="Kubernetes / container readiness probe",
)
async def get_readiness_endpoint(response: Response) -> ReadinessResponse:
    """Verifies that the service can accept incoming traffic (database reachable)."""
    ready, data = await check_readiness()
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return data


@router.get(
    "/liveness",
    response_model=LivenessResponse,
    summary="Kubernetes / container liveness probe",
)
def get_liveness_endpoint() -> LivenessResponse:
    """Ultra-lightweight process heartbeat with zero network or database I/O."""
    return check_liveness()


# --- 2. System and Provider Metrics -------------------------------------------

@router.get(
    "/metrics",
    summary="High-level system metrics overview",
    description="Returns aggregate counts of monitored trains, processed events, latency percentiles, and alerts.",
)
async def get_system_metrics_endpoint(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await get_system_metrics(session)


@router.get(
    "/providers/metrics",
    response_model=ProviderMetricsResponse,
    summary="External railway data provider health and latency metrics",
)
def get_provider_metrics_endpoint() -> ProviderMetricsResponse:
    return data_quality_tracker.get_provider_metrics()


@router.get(
    "/streaming/metrics",
    response_model=StreamingMetricsResponse,
    summary="Real-time Redis Stream lag, throughput, and worker counters",
)
def get_streaming_metrics_endpoint() -> StreamingMetricsResponse:
    metrics = streaming_metrics.get_metrics()
    return StreamingMetricsResponse(
        events_ingested_total=metrics["events_ingested_total"],
        events_debounced_total=metrics["events_debounced_total"],
        predictions_calculated_total=metrics["predictions_calculated_total"],
        network_recalcs_total=metrics["network_recalcs_total"],
        events_out_of_order_total=metrics["events_out_of_order_total"],
        events_duplicate_total=metrics["events_duplicate_total"],
        stream_lag=0,
        latency_percentiles_ms=metrics["latency_ms"],
        worker_status=metrics["worker_status"],
        last_event_time=metrics["last_event_time"],
        last_prediction_time=metrics["last_prediction_time"],
    )


@router.get(
    "/streaming/status",
    summary="Legacy streaming configuration and status summary",
)
def get_streaming_status() -> dict[str, Any]:
    settings = get_settings()
    metrics = streaming_metrics.get_metrics()
    ws_stats = ws_manager.get_connection_stats()
    return {
        "streaming_enabled": settings.STREAMING_ENABLED,
        "worker_status": metrics["worker_status"],
        "redis_streams": {
            "train_events": settings.REDIS_STREAM_TRAIN_EVENTS,
            "predictions": settings.REDIS_STREAM_PREDICTIONS,
            "consumer_group": settings.REDIS_CONSUMER_GROUP,
            "consumer_name": settings.REDIS_CONSUMER_NAME,
        },
        "metrics": metrics,
        "websockets": ws_stats,
    }


# --- 3. Data Quality and Drift Monitoring -------------------------------------

@router.get(
    "/data-quality",
    response_model=DataQualityResponse,
    summary="Telemetry data quality score and dimension breakdown",
)
def get_data_quality_endpoint() -> DataQualityResponse:
    """Evaluates telemetry Completeness, Freshness, Validity, and Consistency (0-100 score)."""
    return data_quality_tracker.compute_data_quality_score()


@router.get(
    "/drift",
    response_model=DriftAnalysisResponse,
    summary="Statistical feature data drift (PSI/KS) and model performance drift",
)
async def get_drift_endpoint(session: AsyncSession = Depends(get_db)) -> DriftAnalysisResponse:
    return await check_drift(session)


# --- 4. MLOps Model Registry, Lifecycle, Promotion & Rollback -----------------

@router.get(
    "/models",
    response_model=ModelCatalogResponse,
    summary="List all registered model versions, metadata, and lifecycle status",
)
def list_models_endpoint() -> ModelCatalogResponse:
    active_ver = model_registry.active_version()
    models_data = model_registry.list_models()

    catalog_models = [
        ModelMetadataResponse(
            model_version=m["model_version"],
            status=m["status"],
            training_timestamp=m["training_timestamp"],
            dataset_version=m["dataset_version"],
            feature_schema_version=m["feature_schema_version"],
            test_mae=m["test_mae"],
            baseline_mae=m["baseline_mae"],
            improvement_percent=m["improvement_percent"],
            uncertainty_level=m["uncertainty_level"],
            artifact_path=m["artifact_path"],
        )
        for m in models_data
    ]

    return ModelCatalogResponse(
        active_model=active_ver,
        staged_model=None,
        models=catalog_models,
    )


@router.get(
    "/models/{model_version}/metrics",
    response_model=ModelEvaluationResponse,
    summary="Detailed prediction evaluation, horizon breakdown, and calibration",
)
async def get_model_metrics_endpoint(
    model_version: str, session: AsyncSession = Depends(get_db)
) -> ModelEvaluationResponse:
    return await evaluate_model_performance(session, model_version=model_version)


@router.post(
    "/models/{model_version}/promote",
    summary="Safely promote candidate model to PRODUCTION (Quality Gate validated)",
)
def promote_model_endpoint(
    model_version: str,
    force: bool = Query(default=False, description="Force promotion bypassing quality gate"),
    reason: str | None = Query(default=None, description="Promotion justification"),
    admin_user: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    previous_active = model_registry.active_version()
    success, message = model_registry.promote_model(
        candidate_version=model_version,
        actor=admin_user,
        reason=reason,
        force=force,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    audit_logger.record_event(
        action="MODEL_PROMOTION",
        actor=admin_user,
        previous_value=previous_active,
        new_value=model_version,
        reason=reason or ("Forced promotion" if force else "Quality gate validated"),
    )
    return {
        "status": "PROMOTED",
        "model_version": model_version,
        "previous_active": previous_active,
        "message": message,
    }


@router.post(
    "/models/rollback",
    summary="Rollback production model pointer to a previous model version",
)
def rollback_model_endpoint(
    payload: RollbackRequest,
    admin_user: str = Depends(verify_admin_key),
) -> dict[str, Any]:
    previous_active = model_registry.active_version()
    success, message = model_registry.rollback_model(
        target_version=payload.target_version,
        actor=admin_user,
        reason=payload.reason,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    audit_logger.record_event(
        action="MODEL_ROLLBACK",
        actor=admin_user,
        previous_value=previous_active,
        new_value=payload.target_version,
        reason=payload.reason or "Administrative rollback",
    )
    return {
        "status": "ROLLED_BACK",
        "active_model_version": payload.target_version,
        "previous_active": previous_active,
        "message": message,
    }


# --- 5. Security & Audit Logging ---------------------------------------------

@router.get(
    "/audit-log",
    response_model=list[AuditLogEntry],
    summary="Retrieve persistent audit log of sensitive system and MLOps mutations",
)
def get_audit_log_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    _admin: str = Depends(verify_admin_key),
) -> list[AuditLogEntry]:
    return audit_logger.get_entries(limit=limit)


# --- 6. Operational & Predictive System Alerts --------------------------------

@router.get(
    "/alerts",
    response_model=list[AlertRead],
    summary="Active operational and predictive system alerts",
)
async def get_active_alerts_endpoint(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> list[AlertRead]:
    alerts, _ = await alert_repository.list_active_paginated(session, offset=offset, limit=limit)
    return alerts
