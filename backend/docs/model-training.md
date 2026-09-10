# RAILCAST MLOps & Model Retraining Runbook

This runbook documents the machine learning lifecycle for RAILCAST's ETA residual prediction model (`xgb-residual`), from dataset generation and chronological validation to safe promotion and rollback.

---

## 1. MLOps Architecture & Lifecycle

```
HISTORICAL RAILWAY DATA / SYNTHETIC GENERATOR
                      │
                      ▼
             DATASET VERSIONING
           (dataset-vYYYY-MM-DD)
                      │
                      ▼
           FEATURE SCHEMA VALIDATION
                 (features-v1)
                      │
                      ▼
           CHRONOLOGICAL DATA SPLIT
          Train (70%) / Val (15%) / Test (15%)
                      │
                      ▼
             XGBOOST RETRAINING
           (Reproducible Seed 42)
                      │
                      ▼
           UNCERTAINTY CALIBRATION
          (Residual Quantile Buckets)
                      │
                      ▼
           QUALITY GATE EVALUATION
        (MAE < Active & MAE < Baseline)
                      │
                      ▼
             REGISTER CANDIDATE
         (models/eta_residual/version/)
                      │
                      ▼
          SAFE PROMOTION / ROLLBACK
          (active_model.json pointer)
```

---

## 2. Dataset Versioning & Feature Schemas

Every trained model artifact strictly references:
- **`dataset_version`**: e.g. `dataset-v2026-09-10`.
- **`feature_schema_version`**: `features-v1`.
- **`training_timestamp`**: UTC ISO timestamp.
- **`hyperparameters` & `random_seed`**: Stored in `metadata.json` for experimental reproducibility.

---

## 3. Retraining Workflow

To retrain a candidate model:

```powershell
# Retrain candidate model xgb-residual-v2 (does NOT promote automatically)
python -m scripts.retrain_eta_model --version xgb-residual-v2 --days 90 --seed 42
```

### Script Execution Steps
1. **Data Ingestion & Building**: Assembles historical journey records or synthesizes reproducible observations.
2. **Chronological Splitting**: Splits strictly across journey dates (no intra-journey leakage).
3. **Training**: Trains XGBoost booster with validation-based early stopping (30 rounds).
4. **Evaluation**: Evaluates candidate on held-out test journeys, reporting:
   - Mean Absolute Error (MAE)
   - Root Mean Squared Error (RMSE)
   - Median Absolute Error
   - 90th Percentile Error (P90)
   - Mean Error Bias
5. **Quality Gate Validation**: Automated check against promotion criteria.
6. **Registration**: Persists `model.json`, `feature_schema.json`, and `metadata.json` under `models/eta_residual/{version}/`.

---

## 4. Production Quality Gate

Candidate models are validated against 4 non-negotiable criteria before they can be promoted:

1. **Superiority vs Baseline**: Candidate MAE must be strictly lower than Baseline Engine MAE:
   $$\text{MAE}_{\text{candidate}} < \text{MAE}_{\text{baseline}}$$
2. **Superiority vs Active Model**: Candidate MAE must be less than or equal to current active production model MAE:
   $$\text{MAE}_{\text{candidate}} \le \text{MAE}_{\text{active}}$$
3. **Minimum Improvement Threshold**: Relative improvement over baseline must exceed `MODEL_MIN_IMPROVEMENT_PERCENT` (default $2.0\%$):
   $$\frac{\text{MAE}_{\text{baseline}} - \text{MAE}_{\text{candidate}}}{\text{MAE}_{\text{baseline}}} \ge 2.0\%$$
4. **Statistical Significance**: Held-out test sample size must meet or exceed `MIN_EVALUATION_SAMPLES` (default 30).

---

## 5. Model Promotion & Rollback

### Safe Promotion via CLI
To train and promote in a single step (promotion occurs ONLY if Quality Gate passes):
```powershell
python -m scripts.retrain_eta_model --version xgb-residual-v2 --promote
```

### Promotion via REST API
```bash
curl -X POST "http://localhost:8000/api/v1/system/models/xgb-residual-v2/promote?reason=Improved+validation+MAE" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY"
```

### Model Rollback
If live monitoring detects model degradation or distribution shift, rollback immediately to a known-stable version:
```bash
curl -X POST "http://localhost:8000/api/v1/system/models/rollback" \
  -H "Content-Type: application/json" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY" \
  -d '{"target_version": "xgb-residual-v1", "reason": "Operational rollback due to upstream sensor drift"}'
```

---

## 6. Drift & Performance Degradation Monitoring

- **Feature Data Drift**: `GET /api/v1/system/drift` calculates Population Stability Index (PSI) and 2-sample Kolmogorov-Smirnov statistics across telemetry inputs. Alerts trigger when $\text{PSI} \ge 0.20$.
- **Model Performance Drift**: Compares 7-day rolling live MAE against reference model validation MAE. Flags `MODEL_PERFORMANCE_DRIFT` if error increases by more than $20\%$.
- **Uncertainty Calibration Warning**: Flags `UNCERTAINTY_MISCALIBRATED` if empirical interval coverage drops below $70\%$ or exceeds $90\%$.
