# Agentic AI Design

## 1. Positioning

The system is an **agentic decision-support platform**, not an autonomous policymaker. The dashboard remains the main interface. The agent plans and executes read-only analytical steps, invokes deterministic tools, verifies evidence, and returns both narrative output and dashboard actions.

The MVP uses one orchestrator rather than a multi-agent system.

## 2. Technology stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Orchestration | LangGraph |
| Structured schemas | Pydantic v2 |
| Local model | Ollama-compatible provider |
| AWS model | Amazon Bedrock provider |
| Local checkpoint | SQLite |
| API streaming | FastAPI Server-Sent Events |
| Tool transport | Direct Python calls; MCP/Gateway adapter later |
| Tracing | OpenTelemetry |
| AWS hosting | Amazon Bedrock AgentCore Runtime |

LangGraph is selected because the workflows require explicit state, branching, retries, approval pauses, and deterministic validation nodes. AgentCore can host LangGraph later, so the graph itself remains portable.

## 3. Agent boundaries

The agent may:

- inspect dataset metadata;
- propose schema mappings;
- call validation tools;
- query allowlisted metrics;
- compare districts;
- retrieve forecast and model metrics;
- retrieve quality and lineage information;
- return dashboard filter actions;
- draft an evidence-backed policy brief.

The agent may not:

- execute arbitrary SQL;
- modify or publish data without workflow authorization;
- approve its own low-confidence mapping;
- trigger uncontrolled model deployment;
- claim causality from descriptive relationships;
- hide missing data or uncertainty;
- allocate budgets or send external policy decisions.

## 4. Data onboarding graph

```text
START
  -> load_job
  -> profile_source
  -> retrieve_catalog_context
  -> propose_mapping
  -> validate_mapping
  -> confidence_gate
       -> high confidence -> transform
       -> review needed -> interrupt_for_human
                              -> approved -> transform
                              -> edited -> validate_mapping
                              -> rejected -> END
  -> quality_check
  -> integration_recommendation
  -> publication_gate
  -> publish
  -> emit_refresh_events
  -> END
```

LLM nodes are limited to semantic interpretation and explanation. Parsing, validation, transformation, scoring, and publication are deterministic nodes.

## 5. Policy copilot graph

```text
START
  -> classify_intent
  -> build_analysis_plan
  -> authorize_tools
  -> execute_tool
  -> inspect_result
       -> insufficient -> execute next tool
       -> contradiction -> retrieve provenance/quality
       -> sufficient -> verify_evidence
  -> compose_grounded_answer
  -> derive_dashboard_actions
  -> END
```

Supported intents:

- city overview;
- district profile;
- district comparison;
- historical trend;
- forecast explanation;
- quality/provenance question;
- policy prioritization;
- policy brief generation;
- unsupported/high-risk request.

## 6. Agent state

### 6.1 Ingestion state

```python
class IngestionState(TypedDict):
    job_id: str
    dataset_version_id: str
    source_uri: str
    profile: dict | None
    catalog_context: dict | None
    mapping_proposal: dict | None
    validation_report: dict | None
    approval_status: str
    quality_report: dict | None
    integration_recommendation: dict | None
    curated_uri: str | None
    errors: list[dict]
```

### 6.2 Copilot state

```python
class CopilotState(TypedDict):
    session_id: str
    user_message: str
    dashboard_context: dict
    intent: str | None
    plan: list[dict]
    tool_calls: list[dict]
    evidence: list[dict]
    warnings: list[str]
    answer: str | None
    dashboard_actions: list[dict]
```

## 7. Model provider abstraction

```python
class ModelProvider(Protocol):
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        response_schema: type[BaseModel] | None = None,
    ) -> ModelResponse: ...
```

Implementations:

- `OllamaModelProvider` for offline inference;
- `BedrockModelProvider` for AWS;
- `FakeModelProvider` for deterministic unit tests.

Model selection is configuration, not a hardcoded dependency.

## 8. Tool design

Tools use Pydantic request and response models. They return small, explicit payloads suitable for validation and tracing.

### 8.1 Ingestion tools

- `profile_dataset(dataset_version_id)`
- `get_canonical_schema(topic_hint)`
- `get_alias_dictionary(dimension)`
- `validate_mapping(mapping_proposal)`
- `preview_transformation(mapping_proposal, row_limit)`
- `run_quality_checks(dataset_version_id)`
- `find_join_candidates(dataset_version_id)`

### 8.2 Analytics tools

- `get_city_summary(period)`
- `get_district_profile(district_code, period)`
- `compare_districts(district_codes, metrics, period)`
- `get_metric_series(metric_code, filters, period)`
- `get_priority_ranking(policy_focus, period, limit)`

### 8.3 ML tools

- `get_forecast(district_code, horizon, model_version)`
- `get_model_metrics(model_version)`
- `get_forecast_lineage(model_version)`
- `request_training(dataset_version_id)`; restricted to authorized workflows.

### 8.4 Governance tools

- `get_data_quality(dataset_id, version)`
- `get_metric_lineage(metric_code, period)`
- `get_dataset_limitations(dataset_id)`

### 8.5 Dashboard tools

These return instructions to the client rather than mutating server state:

- `select_districts`;
- `set_period`;
- `set_metric`;
- `open_panel`;
- `highlight_evidence`.

## 9. Query safety

The copilot does not receive a generic SQL execution tool. Analytics tools compile typed requests into predefined query templates.

Example request:

```json
{
  "districtCodes": ["23", "17"],
  "metrics": ["youth_population"],
  "period": {"start": "2018-01", "end": "2025-12"}
}
```

The query adapter validates:

- metric allowlist;
- dimension allowlist;
- maximum result size;
- compatible grain;
- authorized dataset scope;
- read-only execution.

## 10. Structured response

```json
{
  "answer": "Shimen shows a larger historical decline than Linkou...",
  "evidence": [
    {
      "datasetId": "fact_youth_population_monthly",
      "datasetVersion": "2026-08-31T120000Z",
      "metric": "youth_population_change_pct",
      "period": "2018-12/2025-12",
      "districtCode": "23",
      "value": -28.5,
      "unit": "percent",
      "isEstimated": false
    }
  ],
  "warnings": [
    "Historical association does not establish a cause for population decline"
  ],
  "dashboardActions": [
    {"type": "SELECT_DISTRICTS", "values": ["23", "17"]},
    {"type": "OPEN_PANEL", "value": "forecast"}
  ],
  "confidence": 0.91
}
```

## 11. Human-in-the-loop

LangGraph interrupt points are used for:

- ambiguous mapping;
- unknown units;
- unsafe or many-to-many integration proposals;
- override of a failed quality rule;
- publication of a new topic;
- any write-affecting tool.

The resume payload contains the reviewer decision and optional edited mapping. The model cannot create an approval identity.

## 12. Memory

MVP memory is intentionally limited:

- conversation state for the current session;
- dashboard context;
- workflow checkpoint;
- no cross-user semantic memory by default.

Long-term memory is unnecessary for data correctness and introduces privacy and evaluation complexity. It can be added after identity and retention policies exist.

## 13. Agent evaluation

Maintain a versioned evaluation set with:

- 20-30 policy questions;
- 10 mapping tasks;
- 5 adversarial or unsafe requests;
- expected tools;
- expected evidence fields;
- prohibited claims;
- acceptable answer properties.

Metrics:

| Metric | Target |
|---|---:|
| Correct tool selection | >= 90% |
| Required evidence present | 100% |
| Unsupported youth-specific claims | 0 |
| Unsafe SQL/tool invocation | 0 |
| Correct human-approval routing | 100% |
| Mapping schema validity | >= 95% before retry, 100% after retry/review |

## 14. Observability

Each turn records:

- session and trace ID;
- model provider and model identifier;
- prompt template version;
- tool names and validated arguments;
- tool latency and result size;
- evidence identifiers;
- final confidence and warnings;
- token/latency metrics when available;
- human interruption and resume events.

Sensitive raw row samples must be redacted or excluded from production traces.
