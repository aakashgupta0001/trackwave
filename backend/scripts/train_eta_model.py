"""Train the ML residual ETA model end-to-end (Phase 6).

    python -m scripts.train_eta_model [--days 90] [--seed 42] [--version xgb-residual-v1]

Loads (or generates) the dataset, trains, evaluates on a chronologically held-out test
period, compares against the baseline, and registers the model + metadata.
"""

from app.ml.training import main

if __name__ == "__main__":
    main()
