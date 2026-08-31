# Forecasting and ML

## 1. Forecasting objective

The initial ML task is:

> Forecast the monthly population aged 18-35 for each New Taipei City district over the next 12 months.

This target is selected because the population source contains single-year ages. The target can therefore be calculated exactly rather than estimated from broad age bands.

## 2. Forecast dataset

Canonical input grain:

```text
period_start x district_code [x gender_code]
```

Required columns:

| Column | Description |
|---|---|
| `item_id` | District or district-gender series identifier |
| `timestamp` | Monthly period start |
| `target` | Youth population count |
| `district_code` | Static category |
| `gender_code` | Optional static category |
| `is_partial_period` | Flags incomplete latest data |
| `dataset_version` | Training lineage |

The default MVP uses one series per district. Gender-separated series may be evaluated as an extension.

## 3. Data window

Recommended initial experiment:

- use ROC years 107-114 for a continuous monthly window;
- exclude partial ROC year 115 from training until complete or explicitly model it as partial;
- backtest using rolling or fixed temporal folds;
- reserve the latest complete 12 months for final evaluation.

ROC year 106 is missing from the population source, so using ROC 107 onward avoids silently imputing an entire year.

## 4. Baselines

Every learned model must be compared with:

### Seasonal naive

```text
forecast(t) = observed(t - 12 months)
```

### Seasonal moving average

Average the same calendar month across recent years.

### Optional gradient-boosted baseline

XGBoost with lag and calendar features:

- lag 1, 3, 6, 12;
- rolling mean 3, 6, 12;
- rolling slope;
- month-of-year;
- district category;
- optional population composition features known at prediction time.

The project must not claim ML improvement unless evaluation demonstrates it.

## 5. Candidate models

### MVP recommendation

Use XGBoost or a compact PyTorch forecasting model implemented through portable training scripts. This allows identical code to run locally and inside a SageMaker Training Job.

### AWS-native experiment

Evaluate SageMaker DeepAR because it trains jointly across related time series and produces probabilistic forecasts. The built-in approach remains an experiment rather than a hard dependency of the offline core.

## 6. Evaluation design

### Temporal backtest

No random train/test split is allowed. Suggested folds:

```text
Fold 1: train through 2022-12, validate 2023-01..2023-12
Fold 2: train through 2023-12, validate 2024-01..2024-12
Fold 3: train through 2024-12, validate 2025-01..2025-12
```

Exact folds depend on validated source coverage.

### Metrics

| Metric | Purpose |
|---|---|
| WAPE | City/district aggregate error, interpretable for counts |
| sMAPE | Relative error across different district sizes |
| MASE | Comparison against naive forecast |
| Interval coverage | Whether actual values fall within P10-P90 as expected |
| Bias | Detect systematic over/under prediction |

Report metrics at city level and by district. Small districts must not disappear inside a city aggregate.

## 7. Model acceptance gate

A candidate may be registered as approved only if:

- required dataset quality checks pass;
- it outperforms the selected baseline on the primary metric or documents why it remains useful;
- no district has catastrophic degradation beyond a configured threshold;
- prediction intervals pass minimum coverage checks;
- inference output schema validates;
- artifacts and environment are reproducible;
- model card and lineage are complete.

If no learned model passes, the system publishes the baseline forecast with an honest label.

## 8. Portable training entrypoints

```text
ml/
  prepare.py
  train.py
  evaluate.py
  inference.py
  requirements.txt
```

Example local command:

```bash
python -m ml.train \
  --train-path data/ml/train.parquet \
  --validation-path data/ml/validation.parquet \
  --model-dir artifacts/models/run-id \
  --config configs/model.yaml
```

The script must:

- read paths from arguments;
- write model artifacts to the requested directory;
- emit metrics as JSON;
- use deterministic seeds where possible;
- avoid importing application web code;
- support container execution without local path assumptions.

## 9. Forecast output contract

```json
{
  "districtCode": "23",
  "forecastStart": "2026-01-01",
  "horizonMonths": 12,
  "modelVersion": "youth-population-v3",
  "datasetVersion": "2026-08-31T120000Z",
  "backtest": {
    "smape": 8.2,
    "wape": 6.9,
    "baselineWape": 8.1
  },
  "predictions": [
    {
      "period": "2026-01-01",
      "p10": 2010,
      "p50": 2080,
      "p90": 2160
    }
  ]
}
```

Batch forecast output is stored as Parquet for analytics and converted to this JSON format by the API.

## 10. Local model registry

Before AWS integration, a filesystem/SQLite registry stores:

- model version;
- run ID;
- algorithm and hyperparameters;
- code commit;
- dataset version;
- training period;
- evaluation metrics;
- artifact URI;
- approval status;
- created timestamp.

Only one version is marked `production` for a given target and horizon.

## 11. SageMaker migration

| Local capability | SageMaker target |
|---|---|
| Prepare script | Processing Step |
| Train script/container | Training Step |
| Metrics JSON | Evaluation Step output |
| Acceptance rule | Condition Step |
| Local registry | SageMaker Model Registry |
| Local batch forecast | Batch Transform or Processing Step |
| Filesystem artifacts | S3 artifacts |

Target pipeline:

```text
ProcessingStep
  -> TrainingStep
  -> EvaluationStep
  -> ConditionStep
       -> passed: RegisterModel -> Batch forecast
       -> failed: retain current production model
```

## 12. Retraining policy

Retraining may be scheduled when:

- a new complete monthly period is published;
- historical target data changes materially;
- model performance monitoring crosses a threshold;
- a reviewer explicitly requests retraining.

Retraining must not run when:

- the new source is unrelated context;
- data is quarantined;
- the latest period is incomplete without an approved strategy;
- target uniqueness or coverage tests fail.

## 13. Interpretability and policy use

The forecast predicts population trajectory, not policy causation. Contextual education, income, migration, or marriage variables may support descriptive segmentation but should not be presented as causes without an appropriate research design.

The dashboard displays:

- observed and forecast values;
- uncertainty interval;
- baseline comparison;
- last training date;
- model and dataset versions;
- missing-data warning;
- plain-language limitation.

## 14. Drift and monitoring

Monitor:

- actual-versus-forecast residuals;
- WAPE/sMAPE by district;
- interval coverage;
- target distribution change;
- missing periods;
- district-level bias;
- training and inference failures.

The MVP can calculate these offline. AWS integration maps them to SageMaker and CloudWatch monitoring workflows.
