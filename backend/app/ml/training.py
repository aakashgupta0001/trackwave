"""Reproducible training pipeline for the ML residual ETA model (Phase 6).

Run as:  python -m app.ml.training [--days 90] [--seed 42] [--version xgb-residual-v1]

Pipeline: load dataset (real history when sufficient, else clearly-labelled SYNTHETIC)
-> validate features -> chronological split (train/val/test at journey-day level) ->
train XGBoost -> evaluate validation + test -> compare against the baseline ->
register the model + feature schema + metrics.

Honesty rule: the printed comparison reports a signed improvement. If ML does not beat
the baseline on the held-out test period, that is reported as negative — the runtime
fallback to the baseline covers this case.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.ml.dataset import (
    DATASET_SOURCE,
    DATASET_TARGET,
    count_historical_actual_arrivals,
    dataframe_from_observations,
    generate_synthetic_observations,
)
from app.ml.evaluation import comparison_table, regression_metrics
from app.ml.features import (
    ENCODED_CATEGORICAL_MAP,
    FEATURE_COLUMNS,
    RAW_CATEGORICAL_COLUMNS as CATEGORICAL_COLUMNS,
    encode_row,
    fit_categorical_encoder,
    row_to_vector,
)
from app.ml.model import feature_importance, model_params, num_boost_round
from app.ml.registry import MODEL_VERSION, ModelRegistry
from app.ml.uncertainty import build_uncertainty_metadata
from app.ml.target import DATASET_SOURCE_HISTORICAL, DATASET_SOURCE_SYNTHETIC

logger = logging.getLogger(__name__)

# A raw dataset carries numeric features + raw categoricals (encoded values are
# derived at encode time, never stored separately).
REQUIRED_COLUMNS = [c for c in FEATURE_COLUMNS if c not in ENCODED_CATEGORICAL_MAP] + CATEGORICAL_COLUMNS + [
    DATASET_TARGET, "prediction_timestamp", "scheduled_arrival", "actual_arrival", "train_number",
]


@dataclass
class SplitResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    boundaries: dict = field(default_factory=dict)


def validate_dataset(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    if df.empty:
        raise ValueError("Dataset is empty")
    if df[DATASET_TARGET].isna().all():
        raise ValueError("Target column is entirely NaN")
    # Targets must be finite minutes.
    bad = (~np.isfinite(df[DATASET_TARGET].to_numpy(dtype=float))).sum()
    if bad:
        raise ValueError(f"{bad} non-finite target values")


def chronological_split(
    df: pd.DataFrame, train_ratio: float | None = None, validation_ratio: float | None = None
) -> SplitResult:
    """Split by observation time at journey-day level: whole days go to exactly one
    split, so observations from the same journey can never straddle train/test (which
    a random split would invite)."""
    s = get_settings()
    train_ratio = train_ratio if train_ratio is not None else s.ML_SPLIT_TRAIN
    validation_ratio = validation_ratio if validation_ratio is not None else s.ML_SPLIT_VALIDATION

    df = df.sort_values("prediction_timestamp").reset_index(drop=True)
    df["journey_day"] = pd.to_datetime(df["prediction_timestamp"]).dt.date
    days = sorted(df["journey_day"].unique())

    train_days = max(1, int(len(days) * train_ratio))
    val_days = max(1, int(len(days) * validation_ratio))
    test_days = max(1, len(days) - train_days - val_days)

    train_end = days[train_days]
    val_end = days[train_days + val_days]

    train = df[df["journey_day"] < train_end]
    validation = df[(df["journey_day"] >= train_end) & (df["journey_day"] < val_end)]
    test = df[df["journey_day"] >= val_end]

    return SplitResult(
        train=train.drop(columns=["journey_day"]),
        validation=validation.drop(columns=["journey_day"]),
        test=test.drop(columns=["journey_day"]),
        boundaries={
            "method": "CHRONOLOGICAL_BY_JOURNEY_DAY",
            "train_days": days[:train_days] and f"{days[0]}..{days[train_days - 1]}",
            "validation_days": f"{train_end}..{days[train_days + val_days - 1]}",
            "test_days": f"{val_end}..{days[-1]}",
            "total_days": len(days),
        },
    )


def _matrix(df: pd.DataFrame, encoder) -> tuple[list[list[float]], np.ndarray, list[float], list[float]]:
    """Encode rows and produce (X, y_residual, y_baseline_error, y_scheduled_error).

    baseline/scheduled errors come from stored arrival columns — they exist in the
    dataset already (the actual arrival is only ever a LABEL here, never a feature).
    """
    xs, y = [], []
    baseline_errors: list[float] = []
    scheduled_errors: list[float] = []
    for _, row in df.iterrows():
        encoded = encode_row(row, encoder)
        xs.append(row_to_vector(encoded))
        y.append(float(row[DATASET_TARGET]))
        baseline_errors.append(float(row[DATASET_TARGET]))  # actual - baseline == target
        scheduled_errors.append(
            (row["actual_arrival"] - row["scheduled_arrival"]).total_seconds() / 60.0
        )
    return xs, np.asarray(y, dtype=float), baseline_errors, scheduled_errors


def train_from_dataframe(
    df: pd.DataFrame,
    *,
    version: str | None = None,
    seed: int = 42,
    register: bool = True,
) -> dict:
    """Full training/evaluation pass. Returns a metrics report dict and (by default)
    registers the model + metadata in the registry."""
    validate_dataset(df)

    split = chronological_split(df)
    train_df, val_df, test_df = split.train, split.validation, split.test
    if train_df.empty or test_df.empty:
        raise ValueError("Chronological split produced an empty train or test set")

    # Categorical vocabulary is fit on TRAINING data only (categories are inputs, not
    # targets, but fitting on train alone is the stricter, simpler discipline).
    encoder = fit_categorical_encoder(train_df.to_dict("records"))

    X_train, y_train, _, _ = _matrix(train_df, encoder)
    X_val, y_val, base_err_val, sched_err_val = _matrix(val_df, encoder)
    X_test, y_test, base_err_test, sched_err_test = _matrix(test_df, encoder)

    import xgboost as xgb

    dtrain = xgb.DMatrix(np.asarray(X_train, dtype=np.float32), label=y_train, feature_names=FEATURE_COLUMNS)
    model = xgb.train(model_params(seed=seed), dtrain, num_boost_round=num_boost_round())

    def _preds(X):
        matrix = xgb.DMatrix(np.asarray(X, dtype=np.float32), feature_names=FEATURE_COLUMNS)
        return model.predict(matrix)

    val_preds = _preds(X_val)
    test_preds = _preds(X_test)

    # Metrics: ML MAE = mean|actual - final| where final = baseline + residual_pred,
    # i.e. mean|residual_true - residual_pred|; baseline MAE = mean|residual_true|.
    val_ml = regression_metrics(base_err_val, [b - p for b, p in zip(base_err_val, val_preds)])
    test_ml = regression_metrics(base_err_test, [b - p for b, p in zip(base_err_test, test_preds)])
    val_baseline = regression_metrics(base_err_val, [0.0] * len(base_err_val))
    test_baseline = regression_metrics(base_err_test, [0.0] * len(base_err_test))
    test_scheduled = regression_metrics(sched_err_test, [0.0] * len(sched_err_test)) if sched_err_test else None

    comparison = comparison_table(
        baseline_mae=test_baseline.mae,
        ml_mae=test_ml.mae,
        scheduled_mae=test_scheduled.mae if test_scheduled else None,
    )

    # Phase 7: residual-quantile uncertainty, computed from the SAME held-out test
    # residuals, stored inside the model artifact so model/schema/uncertainty always
    # share one version.
    horizons = test_df["baseline_minutes_ahead"].tolist() if "baseline_minutes_ahead" in test_df.columns else None
    uncertainty_meta = build_uncertainty_metadata(base_err_test, horizons)

    version = version or MODEL_VERSION
    source = df[DATASET_SOURCE].iloc[0] if DATASET_SOURCE in df.columns else DATASET_SOURCE_SYNTHETIC

    report = {
        "model_version": version,
        "dataset_source": source,
        "dataset_rows": int(len(df)),
        "split": split.boundaries,
        "feature_columns": FEATURE_COLUMNS,
        "validation_metrics": {
            "baseline": val_baseline.as_dict(),
            "ml": val_ml.as_dict(),
        },
        "test_metrics": {
            "baseline": test_baseline.as_dict(),
            "ml": test_ml.as_dict(),
            "scheduled": test_scheduled.as_dict() if test_scheduled else None,
        },
        "comparison": comparison,
        "feature_importance_gain": feature_importance(model)[:15],
        "uncertainty": uncertainty_meta,
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
    }

    if register:
        registry = ModelRegistry(get_settings().ML_MODEL_DIR)
        registry.register(
            version=version,
            booster=model,
            encoder=encoder,
            metadata={
                "dataset_source": source,
                "dataset_rows": report["dataset_rows"],
                "split": split.boundaries,
                "test_metrics": report["test_metrics"],
                "comparison": comparison,
                "uncertainty": uncertainty_meta,
                "training_timestamp": report["training_timestamp"],
                "seed": seed,
                "hyperparameters": {
                    "max_depth": get_settings().ML_XGB_MAX_DEPTH,
                    "learning_rate": get_settings().ML_XGB_LEARNING_RATE,
                    "n_estimators": get_settings().ML_XGB_N_ESTIMATORS,
                    "subsample": get_settings().ML_XGB_SUBSAMPLE,
                    "colsample_bytree": get_settings().ML_XGB_COLSAMPLE_BYTREE,
                    "min_child_weight": get_settings().ML_XGB_MIN_CHILD_WEIGHT,
                    "reg_lambda": get_settings().ML_XGB_REG_LAMBDA,
                },
            },
        )
    return report


def load_or_generate_dataset(path: str, *, days: int, seed: int) -> tuple[pd.DataFrame, str]:
    """Real history when enough actual arrivals exist; otherwise SYNTHETIC (labelled).
    Returns (dataframe, source_label)."""
    from app.db.session import AsyncSessionLocal

    async def _count() -> int:
        from app.db.session import check_database_connection

        if not await check_database_connection():
            return 0
        from app.db.session import AsyncSessionLocal as _S

        async with _S() as session:
            return count_historical_actual_arrivals(session)

    from app.ml.target import DATASET_SOURCE_SYNTHETIC

    historical = 0
    try:
        import asyncio

        historical = asyncio.run(_count())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not inspect historical data (%s) — using synthetic dataset", exc)

    if historical >= 500:
        raise NotImplementedError(
            "Historical dataset building from stored predictions arrives with production "
            f"data (found {historical} known outcomes). The schema pipeline supports it; "
            "the labelled synthetic generator is the Phase 6 development source."
        )

    logger.info("Insufficient historical data (%d known outcomes) — generating SYNTHETIC dataset", historical)
    observations = generate_synthetic_observations(days=days, seed=seed)
    return dataframe_from_observations(observations), DATASET_SOURCE_SYNTHETIC


def main() -> None:
    from app.core.logging import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(description="Train the RAILCAST ML residual ETA model")
    parser.add_argument("--days", type=int, default=None, help="Synthetic history length in days")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--version", type=str, default=None)
    parser.add_argument("--dataset-path", type=str, default=None, help="Parquet file to load instead of generating")
    parser.add_argument("--no-register", action="store_true", help="Evaluate only; do not save the model")
    args = parser.parse_args()

    settings = get_settings()
    if args.dataset_path:
        df = pd.read_parquet(args.dataset_path)
        source = df[DATASET_SOURCE].iloc[0] if DATASET_SOURCE in df.columns else "UNKNOWN"
    else:
        df, source = load_or_generate_dataset(
            args.dataset_path or settings.ML_DATASET_PATH,
            days=args.days or settings.ML_SYNTHETIC_DAYS,
            seed=args.seed if args.seed != 42 else settings.ML_SYNTHETIC_SEED,
        )

    report = train_from_dataframe(df, version=args.version, seed=args.seed, register=not args.no_register)

    print(json.dumps(report, indent=2, default=str))
    comparison = report["comparison"]
    print("\n=== Model comparison (held-out TEST period) ===")
    for row in comparison["models"]:
        mae = row["mae_minutes"]
        print(f"{row['model']:<22} MAE {mae if mae is not None else 'n/a'} min")
    print(f"Improvement over baseline: {comparison['improvement_minutes']} min "
          f"({comparison['improvement_percent']}%) — "
          f"{'ML improves' if comparison['ml_improves_over_baseline'] else 'ML does NOT improve; baseline fallback remains active'}")


if __name__ == "__main__":
    main()
