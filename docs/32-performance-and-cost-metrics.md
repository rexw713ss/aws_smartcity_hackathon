# Performance and cost metrics

The copilot records wall-clock duration, Bedrock input/output tokens, and query
scan bytes on each tool trace. The system benchmark turns those raw values into
repeatable service-level measurements:

- request latency: min, mean, p50, p95, p99, and max;
- throughput, error rate, and end-to-end answer-eval pass rate;
- latency by question and by tool;
- raw scan bytes and Athena-projected billable bytes;
- input/output tokens and model cost when model-specific rates are supplied;
- total projected variable cost and cost per request.

Run the local workload with:

```bash
make benchmark-system
```

The command warms every case once, measures five iterations, and writes:

- `artifacts/reports/system-benchmark.json` for dashboards or CI;
- `artifacts/reports/system-benchmark.csv` for sample-level analysis;
- `artifacts/reports/system-benchmark.md` for reviewers.

This default is the steady-state, warm-cache view. Capture a cold-cache run in
a separate artifact with:

```bash
uv run python -m scripts.benchmark_system \
  --iterations 1 --warmup 0 \
  --output-prefix artifacts/reports/system-benchmark-cold
```

To exercise request concurrency or price a Bedrock-backed run:

```bash
uv run python -m scripts.benchmark_system \
  --iterations 20 \
  --concurrency 4 \
  --model-input-usd-per-million <MODEL_INPUT_RATE> \
  --model-output-usd-per-million <MODEL_OUTPUT_RATE>
```

Model rates have no default because Bedrock pricing depends on the exact model
and region. A model invocation whose adapter omits token usage makes model and
total cost explicitly unavailable instead of silently reporting zero.

The Athena projection defaults to USD 5 per TB and a 10 MB minimum per query.
Each query is rounded independently. The local runtime itself uses DuckDB and
incurs no Athena charge; its scan measurements are a projection input, not an
AWS invoice. A zero-byte cached result has no projected Athena charge. Lambda,
S3, Glue, DynamoDB, data transfer, free tiers, and fixed or
provisioned capacity are intentionally excluded.

Additional benchmark entry points used for the full benchmark report are:

```bash
# Deployed API load curve
uv run python -m scripts.benchmark_remote_api --base-url <API_BASE_URL>

# CloudWatch Lambda and Athena measurements
uv run python -m scripts.collect_aws_benchmark_metrics \
  --profile <AWS_PROFILE> --log-group <LOG_GROUP> --workgroup <WORKGROUP>

# Direct Bedrock model latency and token comparison
uv run python -m scripts.benchmark_bedrock_models \
  --profile <AWS_PROFILE> --model <INFERENCE_PROFILE_ID>

# Ingestion and forecast build/read throughput
uv run python -m scripts.benchmark_data_pipeline

# Browser navigation timing against the deployed site
node frontend/scripts/benchmark-page.mjs <SITE_URL>
```

The consolidated measured result is written to
`artifacts/reports/all-benchmarks.md`. AWS windows should be treated as bounded
snapshots: unrelated traffic in the same log group or Athena workgroup during
the selected lookback interval will be included.
