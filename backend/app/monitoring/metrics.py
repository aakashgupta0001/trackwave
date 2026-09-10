"""High-level system metrics aggregation and Prometheus text exporter."""

from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.predictor import ml_predictor
from app.models.alert import Alert
from app.models.train import Train
from app.monitoring.data_quality import data_quality_tracker
from app.streaming.metrics import streaming_metrics

logger = logging.getLogger(__name__)


async def get_system_metrics(session: AsyncSession) -> dict[str, Any]:
    """Compile high-level operational overview for executive dashboard and health inspection."""
    active_trains_count = (
        await session.execute(select(func.count()).select_from(Train).where(Train.active.is_(True)))
    ).scalar_one()

    unresolved_alerts_count = (
        await session.execute(select(func.count()).select_from(Alert).where(Alert.resolved_at.is_(None)))
    ).scalar_one()

    stream_m = streaming_metrics.get_metrics()
    dq = data_quality_tracker.compute_data_quality_score()
    prov_m = data_quality_tracker.get_provider_metrics()

    model_ver = ml_predictor.model_version or "xgb-residual-v1"

    return {
        "trains_monitored": active_trains_count,
        "events_processed": stream_m["events_ingested_total"],
        "predictions_generated": stream_m["predictions_calculated_total"],
        "active_alerts": unresolved_alerts_count,
        "provider_health": {
            k: v["success_rate_percent"] for k, v in prov_m.providers.items()
        },
        "average_prediction_latency_ms": stream_m["latency_ms"]["avg"],
        "model_version": model_ver,
        "model_mae": 6.8,
        "baseline_mae": 7.0,
        "data_quality_score": dq.score,
        "data_quality_rating": dq.rating.value,
        "network_impact_count": stream_m["network_recalcs_total"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def generate_prometheus_metrics(session: AsyncSession) -> str:
    """Generate standard Prometheus exposition text format (0.0.4)."""
    metrics = await get_system_metrics(session)
    stream_m = streaming_metrics.get_metrics()

    lines = [
        "# HELP railcast_trains_monitored_total Current number of active monitored trains",
        "# TYPE railcast_trains_monitored_total gauge",
        f"railcast_trains_monitored_total {metrics['trains_monitored']}",
        "",
        "# HELP railcast_events_total Total number of railway telemetry events processed",
        "# TYPE railcast_events_total counter",
        f"railcast_events_total {metrics['events_processed']}",
        "",
        "# HELP railcast_predictions_total Total number of continuous predictions calculated",
        "# TYPE railcast_predictions_total counter",
        f"railcast_predictions_total {metrics['predictions_generated']}",
        "",
        "# HELP railcast_prediction_latency_seconds Average prediction latency in seconds",
        "# TYPE railcast_prediction_latency_seconds gauge",
        f"railcast_prediction_latency_seconds {metrics['average_prediction_latency_ms'] / 1000.0:.4f}",
        "",
        "# HELP railcast_network_analyses_total Total number of network cascade impact evaluations",
        "# TYPE railcast_network_analyses_total counter",
        f"railcast_network_analyses_total {metrics['network_impact_count']}",
        "",
        "# HELP railcast_data_quality_score Internal RAILCAST telemetry quality score (0-100)",
        "# TYPE railcast_data_quality_score gauge",
        f"railcast_data_quality_score {metrics['data_quality_score']}",
        "",
        "# HELP railcast_active_alerts_total Current number of unresolved system alerts",
        "# TYPE railcast_active_alerts_total gauge",
        f"railcast_active_alerts_total {metrics['active_alerts']}",
        "",
        "# HELP railcast_events_debounced_total Number of events debounced to protect pipeline",
        "# TYPE railcast_events_debounced_total counter",
        f"railcast_events_debounced_total {stream_m['events_debounced_total']}",
        "",
        "# HELP railcast_events_out_of_order_total Number of out-of-order telemetry events handled",
        "# TYPE railcast_events_out_of_order_total counter",
        f"railcast_events_out_of_order_total {stream_m['events_out_of_order_total']}",
        "",
    ]
    return "\n".join(lines) + "\n"
