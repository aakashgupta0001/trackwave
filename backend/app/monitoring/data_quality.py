"""Data quality monitoring and scoring engine for incoming railway telemetry."""

from datetime import datetime, timezone
import logging
import threading
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.train_event import TrainEvent
from app.monitoring.schemas import (
    DataQualityDimension,
    DataQualityRating,
    DataQualityResponse,
    ProviderMetricsResponse,
)
from app.streaming.metrics import streaming_metrics

logger = logging.getLogger(__name__)


class TelemetryQualityTracker:
    """Thread-safe real-time counter for data quality anomalies and provider telemetry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_events: int = 0
        self.missing_coordinates: int = 0
        self.invalid_coordinates: int = 0
        self.missing_speed: int = 0
        self.missing_delay: int = 0
        self.stale_events: int = 0
        self.duplicate_events: int = 0
        self.out_of_order_events: int = 0
        self.unknown_train: int = 0
        self.unknown_station: int = 0
        self.unknown_section: int = 0
        self.provider_failures: int = 0

        # Provider-level metrics: provider_name -> {requests, successes, failures, timeouts, total_latency_ms, stale, malformed}
        self.providers: dict[str, dict[str, Any]] = {
            "SIMULATOR": {"requests": 0, "successes": 0, "failures": 0, "timeouts": 0, "total_latency_ms": 0.0, "stale": 0, "malformed": 0},
            "NTES": {"requests": 0, "successes": 0, "failures": 0, "timeouts": 0, "total_latency_ms": 0.0, "stale": 0, "malformed": 0},
            "RAILRADAR": {"requests": 0, "successes": 0, "failures": 0, "timeouts": 0, "total_latency_ms": 0.0, "stale": 0, "malformed": 0},
        }

    def record_event_telemetry(
        self,
        has_coords: bool,
        coords_valid: bool,
        has_speed: bool,
        has_delay: bool,
        is_stale: bool,
        is_duplicate: bool,
        is_out_of_order: bool,
        unknown_train: bool = False,
        unknown_station: bool = False,
        unknown_section: bool = False,
    ) -> None:
        with self._lock:
            self.total_events += 1
            if not has_coords:
                self.missing_coordinates += 1
            elif not coords_valid:
                self.invalid_coordinates += 1
            if not has_speed:
                self.missing_speed += 1
            if not has_delay:
                self.missing_delay += 1
            if is_stale:
                self.stale_events += 1
            if is_duplicate:
                self.duplicate_events += 1
            if is_out_of_order:
                self.out_of_order_events += 1
            if unknown_train:
                self.unknown_train += 1
            if unknown_station:
                self.unknown_station += 1
            if unknown_section:
                self.unknown_section += 1

    def record_provider_request(
        self,
        provider_name: str,
        success: bool,
        latency_ms: float,
        is_timeout: bool = False,
        is_stale: bool = False,
        is_malformed: bool = False,
    ) -> None:
        name = provider_name.upper()
        with self._lock:
            if name not in self.providers:
                self.providers[name] = {"requests": 0, "successes": 0, "failures": 0, "timeouts": 0, "total_latency_ms": 0.0, "stale": 0, "malformed": 0}
            entry = self.providers[name]
            entry["requests"] += 1
            if success:
                entry["successes"] += 1
            else:
                entry["failures"] += 1
            if is_timeout:
                entry["timeouts"] += 1
            if is_stale:
                entry["stale"] += 1
            if is_malformed:
                entry["malformed"] += 1
            entry["total_latency_ms"] += latency_ms

    def get_provider_metrics(self) -> ProviderMetricsResponse:
        with self._lock:
            output: dict[str, dict[str, Any]] = {}
            for name, data in self.providers.items():
                reqs = data["requests"]
                avg_lat = round(data["total_latency_ms"] / reqs, 2) if reqs > 0 else 0.0
                output[name] = {
                    "requests_total": reqs,
                    "successes_total": data["successes"],
                    "failures_total": data["failures"],
                    "timeouts_total": data["timeouts"],
                    "stale_total": data["stale"],
                    "malformed_total": data["malformed"],
                    "average_latency_ms": avg_lat,
                    "success_rate_percent": round((data["successes"] / reqs) * 100.0, 1) if reqs > 0 else 100.0,
                }
            return ProviderMetricsResponse(providers=output, timestamp=datetime.now(timezone.utc))

    def compute_data_quality_score(self) -> DataQualityResponse:
        """Compute internal RAILCAST 0–100 data quality score and dimensions."""
        with self._lock:
            total = max(1, self.total_events + streaming_metrics.events_ingested_total)
            duplicates = self.duplicate_events + streaming_metrics.events_duplicate_total
            out_of_order = self.out_of_order_events + streaming_metrics.events_out_of_order_total
            missing_c = self.missing_coordinates
            invalid_c = self.invalid_coordinates
            missing_s = self.missing_speed
            missing_d = self.missing_delay
            stale = self.stale_events

        # 1. Completeness (0-25 pts): coordinates, speed, and delay presence
        comp_penalty = ((missing_c * 0.4 + missing_s * 0.3 + missing_d * 0.3) / total) * 25.0
        comp_score = max(0.0, round(25.0 - comp_penalty, 1))

        # 2. Freshness (0-25 pts): ratio of fresh telemetry ticks
        fresh_penalty = (stale / total) * 25.0
        fresh_score = max(0.0, round(25.0 - fresh_penalty, 1))

        # 3. Validity (0-25 pts): valid coordinate bounds and non-negative physical values
        valid_penalty = (invalid_c / total) * 25.0
        valid_score = max(0.0, round(25.0 - valid_penalty, 1))

        # 4. Consistency & Order (0-25 pts): duplicate rate and out-of-order rate
        consistency_penalty = ((duplicates + out_of_order) / total) * 25.0
        consistency_score = max(0.0, round(25.0 - consistency_penalty, 1))

        total_score = round(comp_score + fresh_score + valid_score + consistency_score, 1)

        if total_score >= 80.0:
            rating = DataQualityRating.HIGH
        elif total_score >= 50.0:
            rating = DataQualityRating.MEDIUM
        else:
            rating = DataQualityRating.LOW

        return DataQualityResponse(
            score=total_score,
            rating=rating,
            completeness=DataQualityDimension(
                score=comp_score,
                status="EXCELLENT" if comp_score >= 20 else "DEGRADED",
                description="Coordinates, speed, and delay field completeness",
            ),
            freshness=DataQualityDimension(
                score=fresh_score,
                status="EXCELLENT" if fresh_score >= 20 else "DEGRADED",
                description="Telemetry timeliness within acceptable staleness threshold (120s)",
            ),
            validity=DataQualityDimension(
                score=valid_score,
                status="EXCELLENT" if valid_score >= 20 else "DEGRADED",
                description="Coordinate ranges and physical speed constraints validation",
            ),
            consistency=DataQualityDimension(
                score=consistency_score,
                status="EXCELLENT" if consistency_score >= 20 else "DEGRADED",
                description="Absence of telemetry duplicates and out-of-order arrival anomalies",
            ),
            metrics={
                "events_evaluated_total": total,
                "missing_coordinates": missing_c,
                "invalid_coordinates": invalid_c,
                "missing_speed": missing_s,
                "missing_delay": missing_d,
                "stale_events": stale,
                "duplicate_events": duplicates,
                "out_of_order_events": out_of_order,
                "unknown_train": self.unknown_train,
                "unknown_station": self.unknown_station,
                "unknown_section": self.unknown_section,
                "provider_failures": self.provider_failures,
            },
            timestamp=datetime.now(timezone.utc),
        )


# Shared singleton tracker
data_quality_tracker = TelemetryQualityTracker()
