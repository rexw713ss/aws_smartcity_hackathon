# System Architecture

## 1. Architectural goals

The architecture must satisfy five goals:

1. Run completely offline during backend and AI development.
2. Replace infrastructure adapters with AWS services later without rewriting domain logic.
3. Preserve provenance and prevent unsafe automatic joins.
4. Support human approval inside the ingestion workflow.
5. Keep the dashboard responsive by precomputing expensive analytical and ML results.

## 2. Architectural style

The project follows a ports-and-adapters structure.

```text
┌───────────────────────────────────────────────────────────┐
│ Applications                                              │
│ Dashboard API | Ingestion API | Copilot API | Worker      │
├───────────────────────────────────────────────────────────┤
│ Use cases                                                 │
│ Ingest | Map | Validate | Publish | Forecast | Explain    │
├───────────────────────────────────────────────────────────┤
│ Domain                                                    │
│ Dataset | Schema | Grain | Mapping | Quality | Forecast   │
├───────────────────────────────────────────────────────────┤
│ Ports                                                     │
│ ObjectStore | Catalog | QueryEngine | Model | Workflow    │
├───────────────────────────────────────────────────────────┤
│ Adapters                                                  │
│ Local filesystem/DuckDB/Ollama | S3/Athena/Bedrock       │
└───────────────────────────────────────────────────────────┘
```

Domain and use-case packages may depend on port interfaces. They must not depend on local or AWS implementations.

## 3. Offline reference architecture

```text
Browser
  |
  v
React Dashboard ----SSE/HTTP----> FastAPI
                                    |
               +--------------------+--------------------+
               |                    |                    |
               v                    v                    v
        Ingestion service      Copilot service     Forecast service
               |                    |                    |
               v                    v                    v
       Local filesystem          LangGraph          Local model
       incoming/quarantine       + Ollama           artifacts
               |                    |
               v                    v
       Curated Parquet <------ DuckDB query engine
               |
               v
       SQLite metadata and audit log
```

### Offline responsibilities

- FastAPI accepts files, exposes jobs, serves dashboard metrics, and streams copilot events.
- The ingestion worker profiles, maps, validates, transforms, and publishes data.
- DuckDB queries curated Parquet through registered views.
- SQLite stores dataset metadata, mapping proposals, approvals, and agent checkpoints.
- Ollama provides an optional local model. Deterministic mapping remains available when the model is disabled.
- Local forecasting scripts produce versioned artifacts and batch forecast Parquet files.

## 4. AWS target architecture

```text
User
  |
  v
Web application / Dashboard
  |
  +---------------- API Gateway ----------------+
  |                                             |
  v                                             v
Backend Lambda/container                  AgentCore Runtime
  |                                             |
  |                                      LangGraph + Bedrock
  |                                             |
  +-------------------- tools ------------------+
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
   S3 + Glue          Athena         SageMaker AI
        ^                                 |
        |                                 v
Step Functions <--- EventBridge     Forecast artifacts
  |
  +--> Lambda/Glue processing
  +--> Textract for scanned documents
  +--> approval callback
```

### AWS service ownership

| Capability | AWS service |
|---|---|
| Raw and curated storage | Amazon S3 |
| Workflow state | AWS Step Functions |
| Event trigger | Amazon EventBridge and S3 events |
| Lightweight processing | AWS Lambda |
| Larger ETL | AWS Glue jobs |
| Metadata catalog | AWS Glue Data Catalog |
| Analytical SQL | Amazon Athena |
| Forecast training and batch inference | Amazon SageMaker AI |
| LLM | Amazon Bedrock |
| Agent hosting | Amazon Bedrock AgentCore Runtime |
| Tool gateway, if needed | Amazon Bedrock AgentCore Gateway |
| PDF OCR, future scope | Amazon Textract |
| Operational telemetry | Amazon CloudWatch and AgentCore Observability |

## 5. Stable ports

### 5.1 ObjectStore

```python
class ObjectStore(Protocol):
    def put(self, key: str, content: bytes, metadata: dict) -> str: ...
    def get(self, uri: str) -> bytes: ...
    def list(self, prefix: str) -> list[str]: ...
    def exists(self, uri: str) -> bool: ...
```

- Local adapter: rooted filesystem paths.
- AWS adapter: S3 URIs and object metadata.

### 5.2 DataCatalog

```python
class DataCatalog(Protocol):
    def register(self, dataset: DatasetMetadata) -> None: ...
    def get(self, dataset_id: str) -> DatasetMetadata: ...
    def search_compatible(self, profile: DatasetProfile) -> list[DatasetMetadata]: ...
```

- Local adapter: SQLite with JSON schema columns.
- AWS adapter: Glue Data Catalog plus a metadata table for application-specific fields.

### 5.3 QueryEngine

```python
class QueryEngine(Protocol):
    def execute(self, query: QuerySpec) -> QueryResult: ...
```

The domain uses a typed `QuerySpec`; the adapter owns SQL rendering. This prevents domain code from relying on DuckDB-only SQL or exposing unrestricted SQL to the agent.

### 5.4 ModelProvider

```python
class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
```

- Local adapter: Ollama-compatible HTTP API.
- AWS adapter: Bedrock Runtime.

### 5.5 ForecastService

```python
class ForecastService(Protocol):
    def get_forecast(self, request: ForecastRequest) -> ForecastResult: ...
    def trigger_training(self, request: TrainingRequest) -> TrainingRun: ...
```

- Local adapter: subprocess or in-process training and artifact store.
- AWS adapter: SageMaker Pipeline and Batch Transform.

### 5.6 WorkflowRunner

```python
class WorkflowRunner(Protocol):
    def start_ingestion(self, request: IngestionRequest) -> JobReference: ...
    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None: ...
```

- Local adapter: persisted Python state machine.
- AWS adapter: Step Functions execution and callback token.

## 6. Configuration model

Infrastructure selection is configuration-driven:

```yaml
environment: local
storage:
  provider: filesystem
  root: ./data
catalog:
  provider: sqlite
query:
  provider: duckdb
model:
  provider: ollama
forecast:
  provider: local
```

AWS configuration replaces providers without changing use cases:

```yaml
environment: aws
storage:
  provider: s3
catalog:
  provider: glue
query:
  provider: athena
model:
  provider: bedrock
forecast:
  provider: sagemaker
```

Secrets must come from environment-specific secret storage and never appear in committed YAML.

## 7. Data flow boundaries

### Command path

Commands mutate workflow state:

- upload dataset;
- approve mapping;
- reject dataset;
- publish curated version;
- trigger training.

### Query path

Queries are read-only:

- retrieve job status;
- list datasets;
- get district metrics;
- get forecast;
- compare districts;
- retrieve audit history.

Separating command and query paths simplifies permissions and prevents the policy copilot from acquiring write privileges.

## 8. Deployment portability rules

- Use URI abstractions rather than assuming local paths.
- Keep training and inference entrypoints executable as regular Python commands.
- Store model inputs and outputs in documented file formats.
- Avoid DuckDB-specific functions in shared analytical definitions.
- Keep AWS event payload conversion inside adapters.
- Expose agent tools through ordinary Python functions before adding MCP or Gateway wrappers.
- Require ARM64-compatible dependencies if packaging for AgentCore Runtime containers.
- Use UTC internally and retain the original reporting calendar in metadata.

## 9. Performance approach

- Store curated analytical data as partitioned Parquet.
- Precompute city summaries, district profiles, rankings, and batch forecasts.
- Cache dashboard responses by dataset version and filter set.
- Keep agent tool results small and structured.
- Stream agent progress separately from final grounded output.
- Do not run model training synchronously inside an HTTP request.

## 10. Failure isolation

- A failed new ingestion must not affect the current published dataset version.
- Raw files are immutable.
- Curated publication uses versioned paths and atomic catalog updates.
- Low-quality data remains quarantined.
- Model training failure preserves the previous approved forecast.
- Agent failure does not prevent direct dashboard access.
- Dashboard summaries display the timestamp and version of their source data.
