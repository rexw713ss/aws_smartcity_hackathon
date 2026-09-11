# Proposed Project Structure

## 1. Repository layout

```text
aws_smartcity_hackathon/
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   ├── worker/
│   │   └── main.py
│   └── dashboard/
│       └── ...
├── src/
│   └── youth_compass/
│       ├── domain/
│       ├── application/
│       ├── ingestion/
│       ├── mapping/
│       ├── quality/
│       ├── analytics/
│       ├── forecasting/
│       ├── agent/
│       └── ports/
├── adapters/
│   ├── local/
│   └── aws/
├── ml/
│   ├── prepare.py
│   ├── train.py
│   ├── evaluate.py
│   └── inference.py
├── contracts/
│   ├── canonical/
│   ├── api/
│   └── events/
├── configs/
│   ├── base.yaml
│   ├── local.yaml
│   └── aws.example.yaml
├── data/
│   ├── source/
│   ├── incoming/
│   ├── quarantined/
│   ├── standardized/
│   ├── curated/
│   ├── forecasts/
│   └── metadata/
├── artifacts/
│   ├── models/
│   └── reports/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── agent_evals/
├── docs/
├── scripts/
├── pyproject.toml
├── docker-compose.yml
├── Makefile
└── README.md
```

The current Chinese-named source directories live under `data/source/` and remain read-only inputs until migration rules publish canonical tables.

## 2. Domain package

`src/youth_compass/domain/` contains pure entities and policies:

```text
domain/
├── dataset.py
├── schema.py
├── grain.py
├── mapping.py
├── quality.py
├── metric.py
├── forecast.py
├── approval.py
└── errors.py
```

Rules:

- no FastAPI imports;
- no boto3 imports;
- no DuckDB/Ollama imports;
- no filesystem access;
- deterministic and unit-testable.

## 3. Application package

`application/` coordinates domain objects and ports:

```text
application/
├── ingest_dataset.py
├── review_mapping.py
├── publish_dataset.py
├── query_dashboard.py
├── compare_districts.py
├── get_forecast.py
└── generate_policy_brief.py
```

Each use case has explicit request/response models and transaction boundaries.

## 4. Ingestion and mapping packages

```text
ingestion/
├── detection.py
├── csv_parser.py
├── profiler.py
└── sampling.py

mapping/
├── engine.py
├── registry.py
├── transform_registry.py
├── age.py
├── geography.py
├── gender.py
└── time.py

transformation/
├── pipeline.py
├── schema.py
└── values.py
```

`transform_registry.py` defines the allowlist. `values.py` executes deterministic row mappings, while `pipeline.py` owns the offline Parquet and quality-gate vertical slice. No model-produced Python code is executed.

## 5. Quality package

```text
quality/
├── checks.py
├── completeness.py
├── uniqueness.py
├── validity.py
├── consistency.py
├── scoring.py
└── reports.py
```

Checks return structured results rather than throwing on the first data issue. Publication policy decides which failures are fatal.

## 6. Agent package

```text
agent/
├── graphs/
│   ├── onboarding.py
│   └── policy_copilot.py
├── nodes/
├── tools/
├── prompts/
├── state.py
├── schemas.py
└── guardrails.py
```

Prompt templates are versioned files. Tool implementations call application use cases rather than adapters directly.

## 7. Ports and adapters

### Ports

```text
ports/
├── object_store.py
├── catalog.py
├── query_engine.py
├── model_provider.py
├── forecast_service.py
├── checkpoint_store.py
├── event_bus.py
└── clock.py
```

### Local adapters

```text
adapters/local/
├── filesystem_store.py
├── sqlite_catalog.py
├── duckdb_query.py
├── ollama_model.py
├── local_forecast.py
├── sqlite_checkpoint.py
└── inprocess_event_bus.py
```

### AWS adapters

```text
adapters/aws/
├── s3_store.py
├── glue_catalog.py
├── athena_query.py
├── bedrock_model.py
├── sagemaker_forecast.py
├── agentcore_checkpoint.py
└── eventbridge_bus.py
```

AWS adapters can live in the same repository or a separately owned integration package, but they must pass the same contract tests.

## 8. Contracts

`contracts/` is the boundary shared with frontend and AWS integration work:

- canonical field specifications;
- mapping proposal JSON Schema;
- quality report JSON Schema;
- forecast output JSON Schema;
- OpenAPI document;
- event schemas;
- dashboard action schema.

Contract changes require explicit versioning and review.

## 9. Configuration

Configuration precedence:

```text
base.yaml
  -> environment YAML
  -> environment variables
  -> explicit command-line override
```

Configuration models are validated at startup. Secrets are never stored in committed files.

## 10. Data and artifacts in Git

- Existing provided CSV sources remain tracked according to current repository policy.
- New raw uploads, generated Parquet, SQLite files, forecasts, and model artifacts should be ignored by Git.
- Tests use small synthetic or sampled fixtures.
- Large models and generated outputs use local artifact directories or S3.
- Checksums and metadata may be committed only when they are part of a reproducible test fixture.

## 11. Testing layout

### Unit tests

- age overlap;
- ROC year parsing;
- district alias normalization;
- grain inference;
- mapping validation;
- quality scoring;
- ranking calculation.

### Integration tests

- unknown CSV to curated Parquet;
- approval pause and resume;
- DuckDB view registration;
- forecast artifact retrieval;
- copilot tool execution with fake model provider.

### Contract tests

Run the same suite against:

- `DuckDBQueryEngine` and `AthenaQueryEngine`;
- `LocalObjectStore` and `S3ObjectStore`;
- `LocalForecastService` and `SageMakerForecastService`.

### Agent evaluations

Versioned prompts, expected tools, required evidence, and prohibited claims.

## 12. Ownership boundaries

### Backend/AI workstream

- domain model;
- local adapters;
- ingestion and mapping;
- quality engine;
- forecast scripts;
- LangGraph workflows;
- FastAPI contracts;
- agent evaluation.

### AWS integration workstream

- AWS adapters;
- IAM and account setup;
- infrastructure as code;
- deployment pipelines;
- Step Functions/Lambda/Glue integration;
- SageMaker managed pipeline;
- Bedrock/AgentCore deployment;
- CloudWatch integration and cost controls.

### Frontend workstream

- dashboard design;
- map and charts;
- ingestion review UI;
- copilot panel;
- SSE handling;
- dashboard action validation;
- policy brief presentation/export.

## 13. Dependency direction

Allowed:

```text
apps -> application -> domain
adapters -> ports/domain
application -> ports/domain
agent tools -> application
```

Forbidden:

```text
domain -> adapter
domain -> FastAPI
application -> boto3
agent prompt -> direct database
frontend -> storage path
```

This dependency rule is the main protection against a later AWS rewrite.
