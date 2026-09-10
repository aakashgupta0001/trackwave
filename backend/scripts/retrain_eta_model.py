"""Reproducible model retraining, evaluation, and safe promotion pipeline (Phase 10).

Workflow:
1. Load or generate training dataset with explicit dataset versioning.
2. Verify feature schema compatibility against FEATURE_SCHEMA_VERSION.
3. Chronological train/validation/test split at journey-day level.
4. Train candidate XGBoost booster with reproducible seed.
5. Evaluate candidate on held-out test period (MAE, RMSE, Median Error, P90 Error).
6. Calibrate uncertainty residual quantiles.
7. Compare against baseline ETA engine and current active production model.
8. Register candidate in ModelRegistry (lifecycle: CANDIDATE / VALIDATED).
9. Execute strict Quality Gate:
   - Candidate MAE < Baseline MAE
   - Candidate MAE < Active Model MAE
   - Improvement % >= MODEL_MIN_IMPROVEMENT_PERCENT
   - Sample count >= MIN_EVALUATION_SAMPLES
10. Optionally promote if --promote is passed and quality gate is satisfied.

Run as:
    python -m scripts.retrain_eta_model --version xgb-residual-v2 [--promote]
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import sys

import pandas as pd

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.ml.dataset import (
    DATASET_SOURCE,
    DATASET_TARGET,
    dataframe_from_observations,
    generate_synthetic_observations,
)
from app.ml.evaluation import comparison_table, regression_metrics
from app.ml.features import (
    ENCODED_CATEGORICAL_MAP,
    FEATURE_COLUMNS,
    RAW_CATEGORICAL_COLUMNS,
    encode_row,
    fit_categorical_encoder,
    row_to_vector,
)
from app.ml.model import model_params, num_boost_round
from app.ml.registry import model_registry
from app.ml.training import train_from_dataframe

setup_logging()
logger = logging.getLogger("railcast.retrain")


def retrain_pipeline(
    version: str,
    dataset_version: str | None = None,
    days: int = 90,
    seed: int = 42,
    promote: bool = False,
    force_promote: bool = False,
) -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ds_version = dataset_version or f"dataset-v{now.strftime('%Y-%m-%d')}"
    feat_version = settings.FEATURE_SCHEMA_VERSION

    print("\n" + "=" * 80)
    print(f" RAILCAST REPRODUCIBLE MODEL RETRAINING PIPELINE")
    print(f" Candidate Version : {version}")
    print(f" Dataset Version   : {ds_version}")
    print(f" Feature Schema    : {feat_version}")
    print(f" Random Seed       : {seed}")
    print("=" * 80)

    # 1. Dataset Generation / Loading
    logger.info("Building dataset (%d days, seed=%d)...", days, seed)
    observations = generate_synthetic_observations(days=days, seed=seed)
    df = dataframe_from_observations(observations)

    # 2. Reproducible Training, Chronological Split & Evaluation
    logger.info("Executing training, chronological split, evaluation & calibration...")
    report = train_from_dataframe(df, version=version, seed=seed, register=True)

    # 3. Enrich Registry Metadata with Phase 10 Schema & Lifecycle
    model_registry.update_metadata(
        version,
        {
            "dataset_version": ds_version,
            "feature_schema_version": feat_version,
            "status": "CANDIDATE",
        },
    )

    test_metrics = report.get("test_metrics", {})
    ml_m = test_metrics.get("ml", {})
    base_m = test_metrics.get("baseline", {})
    sched_m = test_metrics.get("scheduled") or {}
    comp = report.get("comparison", {})

    # 4. Evaluate Quality Gate
    gate_passed, gate_reason, gate_details = model_registry.validate_candidate(version)

    print("\n" + "=" * 80)
    print(" HELD-OUT TEST EVALUATION RESULTS")
    print("=" * 80)
    print(f"  • Scheduled ETA MAE : {sched_m.get('mae_minutes', 'N/A')} min")
    print(f"  • Baseline ETA MAE  : {base_m.get('mae_minutes')} min")
    print(f"  • Candidate ML MAE  : {ml_m.get('mae_minutes')} min (RMSE: {ml_m.get('rmse_minutes')})")
    print(f"  • Improvement vs Base: {comp.get('improvement_minutes', 0.0):+.2f} min ({comp.get('improvement_percent', 0.0):+.2f}%)")
    print(f"  • Test Sample Count : {ml_m.get('count')}")
    print("-" * 80)
    print(f" QUALITY GATE STATUS  : {'PASSED [VALIDATED]' if gate_passed else 'FAILED [REJECTED]'}")
    print(f" Reason               : {gate_reason}")
    print("=" * 80)

    if gate_passed:
        model_registry.update_metadata(version, {"status": "VALIDATED"})
    else:
        model_registry.update_metadata(version, {"status": "REJECTED", "rejection_reason": gate_reason})

    # 5. Optional Promotion
    if promote or force_promote:
        if gate_passed or force_promote:
            success, msg = model_registry.promote_model(version, actor="retrain_script", force=force_promote)
            print(f"\n PROMOTION RESULT: {msg}\n")
        else:
            print(f"\n PROMOTION SKIPPED: Candidate failed quality gate ({gate_reason})\n")

    return {
        "version": version,
        "dataset_version": ds_version,
        "gate_passed": gate_passed,
        "metrics": test_metrics,
        "comparison": comp,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RAILCAST Model Retraining & Validation Pipeline")
    parser.add_argument("--version", type=str, required=True, help="Target model version (e.g. xgb-residual-v2)")
    parser.add_argument("--dataset-version", type=str, default=None, help="Dataset identifier")
    parser.add_argument("--days", type=int, default=90, help="Days of training history")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--promote", action="store_true", help="Promote candidate to PRODUCTION if quality gate passes")
    parser.add_argument("--force-promote", action="store_true", help="Force promotion bypassing quality gate")
    args = parser.parse_args()

    retrain_pipeline(
        version=args.version,
        dataset_version=args.dataset_version,
        days=args.days,
        seed=args.seed,
        promote=args.promote,
        force_promote=args.force_promote,
    )


if __name__ == "__main__":
    main()
