"""Streaming metrics tracker for continuous prediction pipeline observability."""

from collections import deque
from datetime import datetime, timezone
import threading
from typing import Any


class StreamingMetricsTracker:
    """Thread-safe / task-safe counters and latency percentiles for the streaming pipeline."""

    def __init__(self, latency_window_size: int = 1000) -> None:
        self._lock = threading.Lock()
        self.events_ingested_total: int = 0
        self.events_debounced_total: int = 0
        self.predictions_calculated_total: int = 0
        self.network_recalcs_total: int = 0
        self.websocket_broadcasts_total: int = 0
        self.events_out_of_order_total: int = 0
        self.events_duplicate_total: int = 0
        self.worker_status: str = "INITIALIZING"
        self.last_event_time: datetime | None = None
        self.last_prediction_time: datetime | None = None
        self._latencies: deque[float] = deque(maxlen=latency_window_size)

    def record_event_ingested(self) -> None:
        with self._lock:
            self.events_ingested_total += 1
            self.last_event_time = datetime.now(timezone.utc)

    def record_event_debounced(self) -> None:
        with self._lock:
            self.events_debounced_total += 1

    def record_prediction_calculated(self, latency_ms: float) -> None:
        with self._lock:
            self.predictions_calculated_total += 1
            self.last_prediction_time = datetime.now(timezone.utc)
            self._latencies.append(latency_ms)

    def record_network_recalc(self) -> None:
        with self._lock:
            self.network_recalcs_total += 1

    def record_websocket_broadcast(self) -> None:
        with self._lock:
            self.websocket_broadcasts_total += 1

    def record_out_of_order(self) -> None:
        with self._lock:
            self.events_out_of_order_total += 1

    def record_duplicate(self) -> None:
        with self._lock:
            self.events_duplicate_total += 1

    def set_worker_status(self, status: str) -> None:
        with self._lock:
            self.worker_status = status

    def _percentile(self, sorted_vals: list[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        k = (len(sorted_vals) - 1) * p
        f = int(k)
        c = min(f + 1, len(sorted_vals) - 1)
        d0 = sorted_vals[f] * (c - k)
        d1 = sorted_vals[c] * (k - f)
        return round(d0 + d1, 2)

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            vals = sorted(self._latencies)
            count = len(vals)
            avg_lat = round(sum(vals) / count, 2) if count > 0 else 0.0
            p50 = self._percentile(vals, 0.50)
            p95 = self._percentile(vals, 0.95)
            p99 = self._percentile(vals, 0.99)

            return {
                "worker_status": self.worker_status,
                "events_ingested_total": self.events_ingested_total,
                "events_debounced_total": self.events_debounced_total,
                "predictions_calculated_total": self.predictions_calculated_total,
                "network_recalcs_total": self.network_recalcs_total,
                "websocket_broadcasts_total": self.websocket_broadcasts_total,
                "events_out_of_order_total": self.events_out_of_order_total,
                "events_duplicate_total": self.events_duplicate_total,
                "latency_ms": {
                    "sample_count": count,
                    "avg": avg_lat,
                    "p50": p50,
                    "p95": p95,
                    "p99": p99,
                },
                "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
                "last_prediction_time": self.last_prediction_time.isoformat() if self.last_prediction_time else None,
            }


# Shared singleton tracker
streaming_metrics = StreamingMetricsTracker()
