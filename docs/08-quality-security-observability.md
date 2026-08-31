# Quality, Security, and Observability

## 1. Quality model

Quality is evaluated at three layers:

1. source and data quality;
2. software and contract quality;
3. model and agent quality.

No single numeric score replaces individual blocking checks. A high average score cannot override an unknown unit, unsafe grain, or missing lineage.

## 2. Data quality gates

### Blocking failures

- source cannot be parsed;
- required time or geography dimension cannot be resolved;
- metric unit is unknown for a metric used in arithmetic;
- duplicate keys remain at the declared grain;
- proposed join is many-to-many without aggregation;
- youth-specific label is applied to data with no age dimension;
- row rejection exceeds configured threshold;
- lineage or source checksum is missing;
- output schema fails after writing and reopening Parquet.

### Warnings

- partial period;
- weighted age estimate;
- missing optional district or demographic category;
- historical definition change;
- source update is older than expected;
- low-volume district with unstable forecast.

## 3. Software quality

Required checks before merging implementation changes:

- formatter and linter;
- static type checks for core packages;
- unit tests;
- contract tests;
- integration test for ingestion vertical slice;
- no generated data or secrets added to Git;
- migration compatibility for metadata database;
- documentation update for contract changes.

Recommended initial targets:

| Area | Target |
|---|---:|
| Domain and transformation unit coverage | >= 90% |
| Overall backend coverage | >= 75% |
| Contract test pass rate | 100% |
| Held-out ingestion fixture pass rate | >= 80% in MVP |
| Critical quality-rule false negatives | 0 in test set |

## 4. Security model

### 4.1 Least privilege

Roles are separated into:

- uploader;
- reviewer/data steward;
- policy viewer;
- operator;
- workflow service;
- read-only copilot.

The copilot cannot publish data or approve mappings. Write commands require authenticated application workflows.

### 4.2 File upload controls

- allowlisted extensions and detected media types;
- maximum file and row limits;
- safe filename replacement with generated identifiers;
- no execution of uploaded content;
- spreadsheet formula values treated as data;
- archive extraction disabled in MVP;
- malware scanning hook reserved for AWS deployment;
- raw files stored outside the web server static directory.

### 4.3 Prompt injection and untrusted data

Uploaded cells and document text are untrusted input. The system must:

- delimit source samples from system instructions;
- never interpret data cells as instructions;
- limit sampled rows sent to the model;
- validate every model response against a schema;
- allow only registered transformations and tools;
- keep write operations outside model authority;
- redact secrets and personal information from prompts and traces.

### 4.4 Query controls

- read-only credentials for analytical tools;
- typed query specs rather than raw agent SQL;
- allowlisted tables, metrics, and dimensions;
- query time and scanned-data limits;
- maximum returned rows;
- cancellation and timeout;
- audit of query template and parameters.

## 5. Privacy

The provided repository appears to contain aggregated public statistics, but new uploads may not. Profiling should detect possible direct identifiers and high-cardinality sensitive columns.

MVP behavior:

- warn and quarantine suspected person-level data;
- do not send suspected identifiers to the LLM;
- do not publish person-level rows;
- record retention policy metadata;
- expose only aggregates in dashboard APIs.

## 6. Audit trail

Append-only events record:

```text
dataset.received
dataset.profiled
mapping.proposed
mapping.validated
mapping.reviewed
dataset.transformed
quality.completed
dataset.published
dataset.quarantined
training.requested
model.evaluated
model.approved
forecast.published
agent.tool_called
agent.answer_completed
```

Each event includes actor, timestamp, resource version, trace ID, and relevant decision metadata. Raw model chain-of-thought is neither stored nor displayed.

## 7. Structured logging

Example log event:

```json
{
  "timestamp": "2026-08-31T12:00:08Z",
  "level": "INFO",
  "service": "ingestion-worker",
  "event": "mapping.validated",
  "traceId": "trc_01K...",
  "jobId": "ing_01K...",
  "datasetVersionId": "dsv_01K...",
  "durationMs": 842,
  "qualityScore": 0.87,
  "requiresApproval": true
}
```

Logs should not contain full row samples, credentials, prompts with sensitive content, or model provider secrets.

## 8. Metrics

### Ingestion

- jobs received/completed/failed;
- processing duration by step;
- percentage requiring human review;
- mapping confidence distribution;
- accepted and rejected rows;
- publication latency;
- duplicate upload rate.

### Query/API

- request count and error rate;
- p50/p95 latency;
- query duration and result size;
- cache hit rate;
- active copilot sessions.

### Forecast

- training success/failure;
- training duration;
- WAPE/sMAPE/MASE;
- error and bias by district;
- interval coverage;
- forecast freshness.

### Agent

- tool-selection accuracy on evaluation set;
- schema validation retry rate;
- tool latency;
- answer evidence completeness;
- human-interrupt rate;
- unsupported-claim rate;
- model latency and token usage when available.

## 9. Tracing

OpenTelemetry spans should cover:

```text
HTTP request
  -> application use case
     -> workflow node
        -> model call
        -> tool call
           -> query/storage adapter
```

Trace attributes include stable IDs and versions, not raw sensitive content. The same trace model can export locally and later to AgentCore/CloudWatch observability.

## 10. Availability and recovery

- Current published dataset and forecast remain readable during ingestion failure.
- Every curated version is immutable and rollback-capable.
- SQLite metadata is backed up for local demos.
- DuckDB views can be reconstructed from catalog metadata and Parquet.
- A failed agent response does not block direct dashboard endpoints.
- A failed retraining run retains the previous production model.
- Demo mode includes precomputed forecast artifacts to avoid live-training dependency.

## 11. Cost and resource controls for AWS

- limit Athena scanned bytes and use Parquet partitions;
- batch forecasts rather than always-on endpoints for MVP;
- configure Lambda timeouts and concurrency;
- configure SageMaker job instance and duration limits;
- set S3 lifecycle policies for intermediate artifacts;
- cap model response and context size;
- alarm on unexpected training or model invocation volume;
- use separate development and demo resource tags/budgets.

## 12. Definition of trustworthy output

A dashboard metric or copilot statement is trustworthy only when it includes or can resolve:

- metric definition and unit;
- population scope;
- geographic and temporal grain;
- source dataset and version;
- exact or estimated status;
- quality status;
- transformation lineage;
- forecast/model version when applicable;
- known limitation.
