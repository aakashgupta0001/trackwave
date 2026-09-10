"""Residual target definition (Phase 6).

    residual_minutes = (actual_arrival - baseline_eta) in minutes

Positive: the train arrived later than the baseline predicted. Negative: earlier. The
model learns features -> residual; FINAL ETA = BASELINE ETA + predicted residual.
"""

from __future__ import annotations

from datetime import datetime

DATASET_TARGET = "target_residual_minutes"
DATASET_SOURCE = "dataset_source"
DATASET_SOURCE_SYNTHETIC = "SYNTHETIC"
DATASET_SOURCE_HISTORICAL = "HISTORICAL"


def residual_minutes(actual_arrival: datetime, baseline_eta: datetime) -> float:
    """Signed residual in minutes. Guarded against naive/aware mixing by assuming naive
    datetimes are UTC (consistent with the rest of RAILCAST's prototype scheduling)."""
    if actual_arrival.tzinfo is None:
        from datetime import timezone

        actual_arrival = actual_arrival.replace(tzinfo=timezone.utc)
    if baseline_eta.tzinfo is None:
        from datetime import timezone

        baseline_eta = baseline_eta.replace(tzinfo=timezone.utc)
    return (actual_arrival - baseline_eta).total_seconds() / 60.0


def prediction_error_minutes(actual_arrival: datetime, final_eta: datetime | None) -> float | None:
    """error_minutes = actual_arrival - final_eta (for model monitoring once the
    outcome is known; never during real-time inference)."""
    if final_eta is None:
        return None
    return residual_minutes(actual_arrival, final_eta)
