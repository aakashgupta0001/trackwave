"""Evaluation metrics and the mandatory baseline-vs-ML comparison (Phase 6).

The key business question: does BASELINE + ML RESIDUAL beat BASELINE alone on unseen
(held-out, chronologically latest) data? If not, the report says so — the fallback to
baseline remains available regardless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RegressionMetrics:
    mae: float
    rmse: float
    median_absolute_error: float
    mean_error_bias: float
    count: int

    def as_dict(self) -> dict:
        return {
            "mae_minutes": round(self.mae, 3),
            "rmse_minutes": round(self.rmse, 3),
            "median_absolute_error_minutes": round(self.median_absolute_error, 3),
            "mean_error_bias_minutes": round(self.mean_error_bias, 3),
            "count": self.count,
        }


def regression_metrics(actual: list[float], predicted: list[float]) -> RegressionMetrics:
    if len(actual) != len(predicted):
        raise ValueError("actual/predicted length mismatch")
    if not actual:
        raise ValueError("no observations to evaluate")
    errors = [p - a for a, p in zip(actual, predicted)]
    absolute = [abs(e) for e in errors]
    n = len(errors)
    return RegressionMetrics(
        mae=sum(absolute) / n,
        rmse=math.sqrt(sum(e * e for e in errors) / n),
        median_absolute_error=sorted(absolute)[n // 2] if n % 2 == 1 else (sorted(absolute)[n // 2 - 1] + sorted(absolute)[n // 2]) / 2,
        mean_error_bias=sum(errors) / n,
        count=n,
    )


def comparison_table(
    baseline_mae: float,
    ml_mae: float,
    scheduled_mae: float | None = None,
) -> dict:
    """Baseline vs ML comparison. Improvement is signed: negative means ML is WORSE
    than the baseline alone, and the report must say so."""
    improvement = baseline_mae - ml_mae
    improvement_percent = (improvement / baseline_mae * 100.0) if baseline_mae > 0 else 0.0
    return {
        "models": [
            {"model": "Scheduled ETA", "mae_minutes": round(scheduled_mae, 3) if scheduled_mae is not None else None},
            {"model": "Baseline ETA", "mae_minutes": round(baseline_mae, 3)},
            {"model": "ML Residual ETA", "mae_minutes": round(ml_mae, 3)},
        ],
        "improvement_minutes": round(improvement, 3),
        "improvement_percent": round(improvement_percent, 2),
        "ml_improves_over_baseline": improvement > 0,
    }
