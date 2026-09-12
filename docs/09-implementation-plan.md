# Implementation Plan - Proposed for Approval

> Status: **Approved by the owner on 2026-08-31.**  
> Goal: deliver an offline-first vertical slice, then hand stable contracts to the AWS integration workstream.

## 1. Delivery strategy

Build the smallest end-to-end path first:

```text
held-out CSV
  -> profile
  -> map
  -> validate
  -> approve
  -> curated Parquet
  -> DuckDB
  -> API
  -> dashboard/copy response
  -> forecast
  -> copilot explanation
```

Each phase ends with a reviewable artifact. AWS implementation starts only after the corresponding local port and contract test are stable.

## 2. Workstreams

### Backend and AI workstream

Owner scope:

- canonical contracts;
- domain rules;
- local ingestion;
- data quality;
- DuckDB analytical adapter;
- portable ML scripts;
- LangGraph agent;
- FastAPI;
- automated tests and evaluation fixtures.

### AWS integration workstream

Owner scope:

- AWS account/region/IAM;
- S3, Glue, Athena;
- Lambda, Step Functions, EventBridge;
- SageMaker managed pipeline;
- Bedrock and AgentCore;
- infrastructure as code;
- CloudWatch and budgets.

### Frontend workstream

Owner scope:

- dashboard;
- ingestion review interface;
- forecast visual;
- policy copilot panel;
- dashboard action reducer;
- evidence and quality display.

## 3. Phase 0 - Approval and project bootstrap

Estimated effort: 0.5-1 day.

### Tasks

- Approve MVP and non-goals.
- Confirm competition rules for prebuilt work and external/local models.
- Confirm Python and frontend versions.
- Create `pyproject.toml`, quality commands, and environment configuration.
- Add `.gitignore` rules for generated data, models, SQLite, and secrets.
- Establish package skeleton and CI commands.
- Freeze initial JSON/API contract versions.

### Deliverables

- runnable empty FastAPI health endpoint;
- validated configuration loader;
- repository structure;
- test and lint commands;
- contract files copied from the approved documentation.

### Acceptance criteria

- local setup succeeds from a clean checkout;
- tests run without AWS credentials;
- no existing source CSV is modified;
- generated artifacts do not appear in Git status.

### Approval gate A

Approve project structure, dependencies, and contract names before domain implementation.

## 4. Phase 1 - Canonical domain and deterministic rules

Estimated effort: 1.5-2 days.

### Tasks

- Implement canonical dataset, schema, metric, grain, mapping, and quality models.
- Create district, gender, time, age, education, and marriage dictionaries.
- Implement ROC year conversion.
- Implement district alias normalization.
- Implement age parsing and 18-35 overlap.
- Implement grain uniqueness and safe-join checks.
- Add regression tests for known repository edge cases.

### Deliverables

- `src/youth_compass/domain`;
- transformation registry;
- canonical JSON Schemas;
- unit tests;
- documented sample mappings.

### Acceptance criteria

- all 29 districts normalize to stable codes;
- `15-19` maps to youth weight `0.4`;
- exact age 18-35 maps to weight `1.0`;
- data without age becomes `district_context` or `no_age_dimension`;
- known unsafe many-to-many join fixture is rejected;
- transformation functions contain no LLM dependency.

### Approval gate B

Review canonical schema, metric scope, and weighting assumptions.

## 5. Phase 2 - Offline ingestion vertical slice

Estimated effort: 2-3 days.

Current status: profiling, mapping, deterministic transformation, Parquet verification,
quality/quarantine gates, lineage manifests, idempotent version paths, local object
storage, SQLite catalog, durable approval pause/resume, audit history, and a safe
published-version pointer are implemented. Held-out fixture expansion and a reviewer
HTTP/UI surface remain before Approval gate C.

### Tasks

- Implement local object store and SQLite catalog.
- Implement CSV detection, parsing, sampling, and profiling.
- Implement deterministic mapping baseline using aliases, types, and fuzzy matching.
- Define optional model-assisted mapping provider.
- Validate mapping and calculate evidence-based confidence.
- Implement approval pause/resume.
- Transform and write versioned Parquet.
- Reopen output and verify schema/row counts.
- Implement quality report and quarantine paths.

### Deliverables

- upload-to-Parquet command/API;
- mapping proposal JSON;
- quality report JSON;
- SQLite audit history;
- at least five held-out fixtures.

### Acceptance criteria

- unfamiliar headers are processed without changing code;
- unknown units require review;
- repeated upload is idempotent;
- rejected rows are traceable;
- publication is atomic and rollback-capable;
- entire workflow runs without internet or AWS credentials.

### Approval gate C

Demo held-out ingestion, review UI payload, and curated output before analytics development.

## 6. Phase 3 - Curated analytics and backend API

Estimated effort: 1.5-2 days.

Current status: the safe DuckDB `QueryEngine`, reviewer workflow API, dataset and
lineage endpoints, city summary, district profile/comparison, stable error
envelope, and generated OpenAPI contract are implemented. Population mart
bootstrapping from all source files, trend/ranking pre-aggregations, pagination,
and caching remain before Approval gate D.

### Tasks

- Build canonical population mart from existing source data.
- Register DuckDB views from catalog metadata.
- Implement typed query specs and templates.
- Precompute city summary and district profile.
- Implement dataset, ingestion, district, comparison, quality, and lineage endpoints.
- Generate OpenAPI document and mock responses for frontend.
- Add pagination, caching keys, and error envelope.

### Deliverables

- FastAPI application;
- DuckDB query adapter;
- initial curated population table;
- OpenAPI contract;
- frontend mock payloads.

### Acceptance criteria

- summary values match independent aggregation checks;
- APIs never expose local filesystem paths;
- raw tables cannot be queried through agent-facing endpoints;
- metric response includes scope, unit, quality, and dataset version;
- local and fake query adapters pass shared contract tests.

### Approval gate D

Frontend and AWS owners approve OpenAPI and analytics contracts.

## 7. Phase 4 - Forecasting baseline and portable model

Estimated effort: 2-3 days.

### Tasks

- Build monthly youth population training set.
- Implement seasonal naive and seasonal moving-average baselines.
- Implement candidate XGBoost/PyTorch training path.
- Run temporal backtests.
- Produce district-level metrics and uncertainty output.
- Implement local model registry and batch forecast publication.
- Implement forecast API.
- Document SageMaker Processing/Training/Evaluation entrypoints.

### Deliverables

- reproducible training scripts;
- evaluation report;
- approved baseline or candidate model;
- forecast Parquet and JSON output;
- local model registry record.

### Acceptance criteria

- no random time-series split;
- every district has a forecast or explicit failure reason;
- learned model is not promoted if it fails baseline gate;
- output includes P10/P50/P90 or an explicitly documented substitute;
- training is executable with command-line arguments and no web application imports.

### Approval gate E

Review model choice, backtest, limitations, and AWS migration contract.

## 8. Phase 5 - Agentic workflows

Estimated effort: 2-3 days.

### Tasks

- Implement model provider interface with fake and Ollama adapters.
- Implement LangGraph onboarding graph.
- Implement LangGraph policy copilot graph.
- Wrap application services as Pydantic tools.
- Add typed dashboard actions.
- Add evidence verifier and unsupported-claim guardrails.
- Add SQLite checkpoints and SSE progress events.
- Create agent evaluation dataset and runner.

### Deliverables

- offline agent service;
- tool catalog;
- graph state definitions;
- structured copilot response;
- evaluation report for golden questions.

### Acceptance criteria

- pipeline works with fake model for deterministic tests;
- low-confidence ingestion pauses for human review;
- copilot has no unrestricted SQL or publication tool;
- every policy answer contains evidence or refuses to answer;
- no contextual income/migration metric is described as youth-specific;
- dashboard actions validate before returning.

### Approval gate F

Demo agent traces, tool calls, evidence, failure handling, and dashboard events.

## 9. Phase 6 - Dashboard integration and end-to-end demo

Estimated effort: 1.5-2 days across backend/frontend.

### Tasks

- Connect dashboard to summary, profile, trend, comparison, forecast, and quality APIs.
- Build upload and mapping review flow.
- Connect SSE copilot progress.
- Apply validated dashboard actions.
- Add evidence drawer and limitation badges.
- Prepare precomputed fallback forecast and deterministic demo fixture.
- Rehearse success and failure scenarios.

### Deliverables

- working local demo;
- demo dataset and script;
- screenshots/video fallback;
- final architecture and metric evidence.

### Acceptance criteria

- complete upload-to-insight journey works from a clean local environment;
- invalid file is quarantined without affecting published dashboard data;
- agent and direct dashboard remain independently usable;
- demo finishes in the allocated presentation time;
- no step depends on live model training.

### Approval gate G

Product owner signs off local MVP before AWS cutover.

## 10. AWS integration plan

AWS work can begin after the corresponding local contract stabilizes.

### AWS Phase A - Storage and analytics adapters

- S3 object store;
- Glue catalog;
- Athena typed query adapter;
- contract tests against local equivalents;
- IAM read/write separation.

### AWS Phase B - Managed ingestion workflow

- S3 event/EventBridge trigger;
- Step Functions state machine;
- Lambda/Glue transform steps;
- callback approval workflow;
- failure destinations and retries.

### AWS Phase C - SageMaker

- package portable scripts;
- Processing, Training, Evaluation, Condition, and Register steps;
- Model Registry;
- batch forecast publication;
- CloudWatch metrics and cost limits.

### AWS Phase D - Bedrock and AgentCore

- Bedrock model adapter;
- deploy LangGraph on AgentCore Runtime;
- connect tools through direct AWS SDK adapters or AgentCore Gateway;
- configure identity, trace, and guardrails;
- run the same agent evaluation set.

### AWS Phase E - Deployment hardening

- infrastructure as code;
- environment separation;
- secrets and IAM review;
- budgets and alarms;
- load/latency testing;
- demo deployment and rollback procedure.

## 11. Dependency graph

```text
Phase 0
  -> Phase 1
       -> Phase 2
            -> Phase 3
                 -> Phase 4
                 -> Phase 5
                      -> Phase 6

AWS A starts after Phase 3 contracts
AWS B starts after Phase 2 workflow contract
AWS C starts after Phase 4 model contract
AWS D starts after Phase 5 agent contract
```

## 12. Priority tiers

### P0 - Required for a credible demo

- CSV onboarding;
- canonical schema and deterministic transforms;
- quality report and approval;
- Parquet/DuckDB analytical layer;
- population dashboard API;
- baseline forecast;
- one grounded copilot flow.

### P1 - Strong differentiators

- model-assisted mapping;
- ranking with transparent components;
- dashboard control actions;
- model registry and uncertainty visualization;
- AWS managed adapters.

### P2 - Stretch

- API connectors;
- scanned PDF/Textract;
- scheduled source refresh;
- advanced RAG over policy documents;
- multi-topic feature experiments;
- multi-agent workflows.

## 13. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Too much scope | Enforce P0 before P1/P2 |
| LLM mapping inconsistency | Deterministic baseline, schema validation, human approval |
| Invalid joins | Grain contract and uniqueness checks |
| Model fails baseline | Publish honest baseline forecast |
| AWS integration delay | Keep complete offline demo and stable adapters |
| Dashboard waits on agent | Direct analytics APIs remain independent |
| Live demo latency | Precompute summaries and forecasts |
| Competition rule conflict | Confirm allowed prework before implementation |

## 14. Approved baseline decisions

Approved by the owner on 2026-08-31:

1. MVP supports CSV, modern Excel (`.xlsx`/`.xlsm`), JSON, JSONL, NDJSON, and
   text-based PDF tables; API ingestion and scanned-PDF OCR/Textract remain deferred.
2. Python + FastAPI + LangGraph + Pydantic is the backend/agent stack.
3. Parquet + DuckDB is the offline analytical layer.
4. Ollama is optional; deterministic and fake providers remain first-class.
5. The initial ML target is monthly youth population by district.
6. The first learned model is portable XGBoost/PyTorch; DeepAR is an AWS experiment.
7. Human approval is mandatory for every new topic in MVP.
8. React dashboard work is a separate frontend workstream.
9. AWS adapters are implemented only after local contracts pass review.
10. The existing repository data is treated as input and is not modified in place.
