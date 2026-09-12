# Grounded decision copilot

> Status: grounded local vertical slice and Amazon Bedrock adapter implemented.

## 1. Execution boundary

The copilot separates language interpretation from data execution:

1. `QueryDecomposer` splits the question into typed generic operations.
2. `SmartToolRouter` discovers matching tools in `ToolCapabilityRegistry`.
3. A `CopilotPlanner` proposes an allowlisted `CopilotIntent` when ranking is required.
4. The application resolves a versioned decision profile and its feature requirements.
5. `FeatureProvider` retrieves immutable values with dataset evidence.
6. `DecisionScoringEngine` applies constraints, normalization, and weights.
7. `AnswerComposer` verbalizes only the resulting public grounded payload.
8. `VisualizationBuilder` maps the same typed result into allowlisted chart and table specs.
9. The API returns a structured answer, candidate ranking, visualizations, tool trace, assumptions,
   warnings, and public citations.

The model cannot submit SQL, select an unregistered profile, change profile weights, or
alter structured results. `ModelAnswerComposer` rejects unknown citation IDs and numerical
values absent from the grounded payload; any model-boundary failure falls back to the
deterministic answer. Local storage URIs are deliberately omitted from the public response.

The local runtime advertises `search_catalog`, `inspect_dataset`, `query_observations`,
`compare_entities`, `forecast_metric`, `get_features`, `rank_candidates`, and
`explain_lineage` through
`GET /api/v1/copilot/capabilities`. It can inspect published canonical datasets and answer
grounded trend/comparison questions without a use-case-specific feature mart. It retrieves
published local forecasts with uncertainty and model lineage. A runtime without a configured
forecast adapter returns the missing operation and refuses to manufacture a partial answer.

The observation tools execute only typed `QuerySpec` requests against allowlisted canonical
fields. They enforce dataset quality, entity and time scope, compatible units and population
scope, query row limits, and at least two periods per compared entity. Percentage changes are
calculated deterministically rather than by the language model.

## 2. Implemented scenarios

- `home_buying@v1`
- `ev_charger_placement@v1`

These profiles reuse feature contracts such as `transit_accessibility`. A new use case
adds a decision profile and only genuinely new feature definitions; it does not require
a separate feature mart.

## 3. API

```http
POST /api/v1/copilot/query
Content-Type: application/json

{
  "question": "Nên đặt trụ sạc xe ở đâu?",
  "entityIds": ["site-a", "site-b"],
  "minQualityScore": 0.7
}
```

When evidence is missing, the endpoint returns `insufficient_data` and does not produce
a recommendation. Unsupported questions return `unsupported_question` without querying
the feature store.

The local runtime reads `data/features/current.parquet`. The Streamlit dashboard exposes
the same endpoint under **Decision copilot**.

## 4. Bedrock integration

`BedrockModelProvider` implements the asynchronous `ModelProvider` port with Amazon
Bedrock's Converse API. It uses `outputConfig.textFormat` when a response schema is present,
validates the returned JSON again in the application, configures bounded SDK retries and
timeouts, and translates SDK failures into `ModelInvocationError`. The blocking boto3 call
runs outside the event loop.

Enable it with:

```bash
export YOUTH_COMPASS_MODEL__PROVIDER=bedrock
export YOUTH_COMPASS_MODEL__MODEL_ID=<model-or-inference-profile-id>
export YOUTH_COMPASS_MODEL__REGION=us-east-1
```

`REGION` must match the code default (`us-east-1`); Bedrock model access is granted per
account **and** per region, so pointing at a region where the model is not enabled fails at
invocation, not at startup. Take `MODEL_ID` verbatim from the Bedrock console's Model access
page for that account and region — it is not guessable, and an inference-profile id differs
from a base model id.

AWS credentials use the standard boto3 credential chain and are never stored in application
configuration. Because each shell starts fresh, credentials exported in an interactive
terminal are invisible to a separately launched server or test run; persist them to
`~/.aws/credentials` with `scripts/aws_persist_session.sh` so the whole chain sees them.

The API runtime uses Bedrock for `ModelQueryDecomposer` and `ModelAnswerComposer`, with
deterministic fallbacks for transient or invalid model responses. The task role needs
`bedrock:InvokeModel` for the configured model or inference profile. Retrieval, scoring,
constraints, evidence, and the final structured result remain deterministic application
responsibilities.

**Verify Bedrock is actually being used.** The fallbacks are deliberate and keep answers
correct and grounded when the model is unreachable — which means a misconfigured provider
looks exactly like a working one. Two signals distinguish them:

- the response `tool_trace` reports `answer_composer` with outcome `model` when Bedrock
  answered and `deterministic` when it did not;
- the application logs a warning naming the failure, for example
  `answer composer fell back to the deterministic template: Bedrock invocation failed:
  Unable to locate credentials`.

Check one of those before treating a demo as running on Bedrock.

## 5. Verification

The suite covers English and Taiwan Traditional Chinese decomposition prompts, both reference decisions,
generic observation trends, hard feasibility constraints, entity filters, period filters,
minimum evidence quality, missing snapshots, unsupported questions, citation redaction,
API execution, and the model-planner allowlist.

The versioned routing dataset is `evals/agent-routing.jsonl`. Run it offline in CI with:

```bash
make agent-evals
```

To evaluate the configured Bedrock model without hiding failures behind fallback:

```bash
uv run python -m scripts.run_agent_evals --provider bedrock
```

The JSON report includes per-case decompositions, routed plans, exact mismatches, and aggregate
pass rate. The initial dataset covers 12 English and Traditional Chinese decision, trend, discovery,
forecast-gap, and clarification cases.
