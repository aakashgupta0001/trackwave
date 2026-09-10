"""Build the ML residual dataset (Phase 6).

    python -m scripts.build_ml_dataset [--days 90] [--seed 42] [--out data/ml/eta_residual_dataset.parquet]

Uses stored historical predictions with known actual arrivals when enough exist; the
prototype dataset has none, so the output is a clearly-labelled SYNTHETIC dataset
(see app/ml/dataset.py). Never commit generated datasets to Git.
"""

import argparse
import asyncio
import logging

import pandas as pd

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.ml.dataset import (
    DATASET_SOURCE,
    count_historical_actual_arrivals,
    dataframe_from_observations,
    generate_synthetic_observations,
)
from app.ml.target import DATASET_SOURCE_HISTORICAL, DATASET_SOURCE_SYNTHETIC

logger = logging.getLogger(__name__)

MIN_HISTORICAL_ROWS = 500


async def _count_historical() -> int:
    from app.db.session import AsyncSessionLocal, check_database_connection

    if not await check_database_connection():
        logger.warning("PostgreSQL unreachable — cannot inspect historical outcomes")
        return 0
    async with AsyncSessionLocal() as session:
        return count_historical_actual_arrivals(session)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Build the ML residual ETA dataset")
    parser.add_argument("--days", type=int, default=None, help="Synthetic history length in days")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    settings = get_settings()
    out_path = args.out or settings.ML_DATASET_PATH
    historical = asyncio.run(_count_historical())

    if historical >= MIN_HISTORICAL_ROWS:
        raise NotImplementedError(
            f"{historical} historical outcomes exist — wiring the HISTORICAL extraction "
            "into this script is future work once production data accumulates. The "
            "SYNTHETIC generator below remains the labelled development source."
        )

    logger.info(
        "Historical outcomes available: %d (need %d) — generating a SYNTHETIC dataset. "
        "All rows are labelled dataset_source=SYNTHETIC and must not be presented as "
        "real-world railway performance.",
        historical, MIN_HISTORICAL_ROWS,
    )
    observations = generate_synthetic_observations(
        days=args.days or settings.ML_SYNTHETIC_DAYS,
        seed=args.seed if args.seed is not None else settings.ML_SYNTHETIC_SEED,
    )
    df = dataframe_from_observations(observations)

    from pathlib import Path

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows (%s) to %s", len(df), df[DATASET_SOURCE].iloc[0], out_path)


if __name__ == "__main__":
    main()
