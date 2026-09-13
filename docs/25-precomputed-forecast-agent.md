# Precomputed Forecast Agent Tool

## Runtime contract

The first production forecast slice is retrieval-only. The API reads
`data/forecasts/current.parquet` through `PrecomputedParquetForecastService`; it never trains a
model during a user request. A future S3 or SageMaker adapter can implement the same
`ForecastService` port without changing the agent flow.

Required Parquet columns:

| Column | Meaning |
| --- | --- |
| `metric_code` | Canonical metric selected from the published dataset catalog |
| `district_code` | Canonical geography identifier |
| `year_gregorian` | Forecast year |
| `value` | Point estimate |
| `lower`, `upper` | Uncertainty interval containing `value` |
| `model_version` | Immutable model or baseline version |
| `generated_at` | Forecast publication timestamp |

The adapter selects the newest model version generated on or before the request date, applies
the requested district and horizon, and fails closed when the artifact, district, schema, or
uncertainty interval is invalid.

## Agent flow

```text
question
  -> search_catalog
  -> inspect_dataset
  -> forecast_metric
  -> explain_lineage
  -> answer_composer
  -> line + table visualization specs
```

The response exposes the typed `forecast_result`, the source dataset citation, the model
version, assumptions, and the limitation that prediction is not evidence of policy causation.

## Publishing locally

`make forecast` generates the cohort artifact and its model card; see
`docs/31-youth-population-forecast.md`. The reader also accepts the optional driver columns and
attaches the model card only when its `model_version` and `generated_at` match the artifact.

Generate a complete temporary Parquet file, validate it, and atomically promote it to
`data/forecasts/current.parquet`. Do not overwrite the current artifact until all districts,
horizons, model versions, timestamps, and intervals pass validation. Generated forecast files
remain ignored by Git.

The deployed API uses `forecast.provider: s3`, which reads the same two files from the
forecasts bucket (`docs/31`, Deployment).

AWS runtimes that still configure `forecast.provider: sagemaker` do not advertise this local
tool. They continue to fail closed until an AWS forecast adapter or published-artifact reader is
configured.
