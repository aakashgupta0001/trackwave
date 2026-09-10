"""ETA uncertainty via residual-error quantiles (Phase 7).

Method: at training time, the signed residuals (actual − baseline) of the held-out
evaluation data are summarized by their lower/upper quantiles (nominal 80% interval →
P10/P90 of the residual distribution). The interval around any FINAL ETA is then:

    lower_eta = final_eta + residual_p10
    upper_eta = final_eta + residual_p90

The distribution is NOT assumed symmetric — P10 and P90 can have different magnitudes.
Quantiles are stored in the model artifact's metadata (uncertainty block) so model,
feature schema, and uncertainty statistics always belong to the SAME version.

Conditional variant: quantiles are also computed per prediction-horizon bucket (longer
journeys → wider intervals). Groups below UNCERTAINTY_MIN_GROUP_SIZE fall back to the
global quantiles — sparse groups are never used. If no uncertainty metadata exists for
the active model version at all, the interval is reported as unavailable — never
invented.

Calibration (also stored in metadata): empirical coverage = share of held-out actual
arrivals inside [lower, upper]; average interval width. Wording discipline: this is an
"80% prediction interval" whose empirical coverage is measured — never "80% accurate".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import get_settings

logger = logging.getLogger(__name__)

UNCERTAINTY_METHOD = "RESIDUAL_QUANTILES"


@dataclass
class ResidualQuantiles:
    lower_quantile_value: float  # signed, e.g. -5.2 (minutes)
    upper_quantile_value: float  # signed, e.g. +13.4 (minutes)
    sample_count: int

    def as_dict(self) -> dict:
        return {
            "lower_quantile_value_minutes": round(self.lower_quantile_value, 3),
            "upper_quantile_value_minutes": round(self.upper_quantile_value, 3),
            "sample_count": self.sample_count,
        }


def residual_quantiles(residuals: list[float], level: float | None = None) -> ResidualQuantiles:
    """Signed empirical quantiles of the residual distribution at the configured
    interval level (0.80 → P10/P90)."""
    if not residuals:
        raise ValueError("no residuals to quantify")
    level = level if level is not None else get_settings().UNCERTAINTY_INTERVAL_LEVEL
    if not 0 < level < 1:
        raise ValueError(f"interval level must be in (0, 1), got {level}")
    alpha_low = (1 - level) / 2
    alpha_high = 1 - alpha_low
    return ResidualQuantiles(
        lower_quantile_value=float(np_quantile(residuals, alpha_low)),
        upper_quantile_value=float(np_quantile(residuals, alpha_high)),
        sample_count=len(residuals),
    )


def np_quantile(values: list[float], q: float) -> float:
    import numpy as np

    return float(np.quantile(np.asarray(values, dtype=float), q))


def calibrate_coverage(
    residuals: list[float], lower_value: float, upper_value: float
) -> dict:
    """Empirical interval calibration: coverage and average width on held-out data."""
    if not residuals:
        raise ValueError("no residuals to calibrate")
    inside = [r for r in residuals if lower_value <= r <= upper_value]
    widths = [upper_value - lower_value] * len(residuals)
    return {
        "coverage": round(len(inside) / len(residuals), 4),
        "average_interval_width_minutes": round(sum(widths) / len(widths), 3),
        "sample_count": len(residuals),
    }


def build_uncertainty_metadata(test_residuals: list[float], horizons_minutes: list[float] | None = None) -> dict | None:
    """Compute the uncertainty block stored with the model artifact: global quantiles,
    horizon-bucketed conditional quantiles, and test-set calibration. Returns None when
    there is nothing to summarize."""
    if not test_residuals:
        return None
    s = get_settings()
    level = s.UNCERTAINTY_INTERVAL_LEVEL
    global_q = residual_quantiles(test_residuals, level)
    metadata: dict = {
        "method": UNCERTAINTY_METHOD,
        "interval_level": level,
        "lower_quantile": round((1 - level) / 2, 4),
        "upper_quantile": round(1 - (1 - level) / 2, 4),
        "global": global_q.as_dict(),
        "conditional": {"grouping": "PREDICTION_HORIZON_BUCKET", "bucket_minutes": s.UNCERTAINTY_HORIZON_BUCKET_MINUTES,
                        "min_group_size": s.UNCERTAINTY_MIN_GROUP_SIZE, "buckets": {}},
        "calibration": calibrate_coverage(test_residuals, global_q.lower_quantile_value, global_q.upper_quantile_value),
    }

    if horizons_minutes and len(horizons_minutes) == len(test_residuals):
        bucket_minutes = s.UNCERTAINTY_HORIZON_BUCKET_MINUTES
        buckets: dict[int, list[float]] = {}
        for residual, horizon in zip(test_residuals, horizons_minutes):
            key = int(horizon // bucket_minutes) * bucket_minutes
            buckets.setdefault(key, []).append(residual)
        for key, residuals in sorted(buckets.items()):
            if len(residuals) < s.UNCERTAINTY_MIN_GROUP_SIZE:
                continue  # sparse group → inference falls back to global; never used
            metadata["conditional"]["buckets"][str(key)] = residual_quantiles(residuals, level).as_dict()
    return metadata


@dataclass
class PredictionInterval:
    available: bool
    lower_eta: datetime | None = None
    upper_eta: datetime | None = None
    interval_level: float | None = None
    interval_width_minutes: float | None = None
    source: str | None = None  # GLOBAL_QUANTILES / HORIZON_BUCKET_QUANTILES
    reason: str | None = None  # set when unavailable


def prediction_interval(
    uncertainty_metadata: dict | None,
    final_eta: datetime | None,
    baseline_minutes_ahead: float | None,
) -> PredictionInterval:
    """Interval for one station's FINAL ETA using the ACTIVE model's own uncertainty
    metadata (version compatibility is structural: the metadata travels inside the
    loaded artifact). Fallback chain: horizon-bucket quantiles → global quantiles →
    unavailable (clearly marked, never invented)."""
    if final_eta is None:
        return PredictionInterval(available=False, reason="NO_FINAL_ETA")
    if not uncertainty_metadata or uncertainty_metadata.get("method") != UNCERTAINTY_METHOD:
        return PredictionInterval(available=False, reason="NO_UNCERTAINTY_METADATA")

    quantiles = None
    source = None
    bucket = None
    if baseline_minutes_ahead is not None and baseline_minutes_ahead == baseline_minutes_ahead:  # not NaN
        bucket_minutes = uncertainty_metadata.get("conditional", {}).get("bucket_minutes")
        buckets = uncertainty_metadata.get("conditional", {}).get("buckets", {})
        if bucket_minutes and bucket_minutes > 0:
            bucket = int(max(0.0, baseline_minutes_ahead) // bucket_minutes) * bucket_minutes
            match = buckets.get(str(bucket))
            if match is not None:
                quantiles, source = match, "HORIZON_BUCKET_QUANTILES"
    if quantiles is None:
        quantiles = uncertainty_metadata.get("global")
        source = "GLOBAL_QUANTILES"
    if quantiles is None:
        return PredictionInterval(available=False, reason="NO_UNCERTAINTY_METADATA")

    lower_value = float(quantiles["lower_quantile_value_minutes"])
    upper_value = float(quantiles["upper_quantile_value_minutes"])
    return PredictionInterval(
        available=True,
        lower_eta=final_eta + timedelta(minutes=lower_value),
        upper_eta=final_eta + timedelta(minutes=upper_value),
        interval_level=float(uncertainty_metadata.get("interval_level", 0.80)),
        interval_width_minutes=round(upper_value - lower_value, 3),
        source=source,
    )
