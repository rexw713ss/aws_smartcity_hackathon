# Grounded decision copilot

> Status: offline vertical slice implemented; Amazon Bedrock adapter pending.

## 1. Execution boundary

The copilot separates language interpretation from data execution:

1. `QueryDecomposer` splits the question into typed generic operations.
2. `SmartToolRouter` discovers matching tools in `ToolCapabilityRegistry`.
3. A `CopilotPlanner` proposes an allowlisted `CopilotIntent` when ranking is required.
4. The application resolves a versioned decision profile and its feature requirements.
5. `FeatureProvider` retrieves immutable values with dataset evidence.
6. `DecisionScoringEngine` applies constraints, normalization, and weights.
7. The API returns a structured answer, candidate ranking, tool trace, assumptions,
   warnings, and public citations.

The model cannot submit SQL, select an unregistered profile, change profile weights,
or manufacture citations. Local storage URIs are deliberately omitted from the public
response.

The current runtime advertises `search_catalog`, `inspect_dataset`, `query_observations`,
`compare_entities`, `get_features`, `rank_candidates`, and `explain_lineage` through
`GET /api/v1/copilot/capabilities`. It can inspect published canonical datasets and answer
grounded trend/comparison questions without a use-case-specific feature mart. Forecast and
source-acquisition requests are decomposed, but the router returns their missing operations
and refuses to manufacture a partial answer until those tools are registered.

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
export YOUTH_COMPASS_MODEL__REGION=ap-northeast-1
```

The API runtime then uses Bedrock for `ModelQueryDecomposer`, with
`DeterministicQueryDecomposer` as a fail-safe for transient model failures. The task role
needs `bedrock:InvokeModel` for the configured model or inference profile. AWS credentials
continue to use the standard boto3 credential chain and are never stored in application
configuration.

Bedrock should initially be used for intent classification and later for narrative
wording. Retrieval, scoring, constraints, evidence, and the final structured result remain
deterministic application responsibilities.

## 5. Verification

The suite covers Vietnamese and English decomposition prompts, both reference decisions,
generic observation trends, hard feasibility constraints, entity filters, period filters,
minimum evidence quality, missing snapshots, unsupported questions, citation redaction,
API execution, and the model-planner allowlist.
