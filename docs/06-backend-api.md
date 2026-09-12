# Backend API Contract

> Implementation note: the offline reviewer, catalog, city summary, district
> profile, and district comparison vertical slice is implemented. Forecast,
> copilot, priority ranking, trend, authentication, and pagination remain target
> contracts. See [`16-reviewer-dashboard-api.md`](./16-reviewer-dashboard-api.md).

## 1. API goals

The backend exposes stable contracts to the dashboard and agent while hiding whether the implementation uses local adapters or AWS services.

API principles:

- versioned under `/api/v1`;
- JSON for metadata and analytics;
- multipart upload for source files;
- asynchronous jobs for ingestion and training;
- SSE for long-running agent progress;
- consistent error envelope;
- identifiers rather than filesystem paths in public responses;
- read-only analytical endpoints separated from mutation endpoints.

## 2. Service modules

```text
FastAPI application
  ├── ingestion routes
  ├── dataset/catalog routes
  ├── analytics routes
  ├── forecast routes
  ├── copilot routes
  └── health/operations routes
```

## 3. Ingestion endpoints

### `POST /api/v1/datasets/upload`

Creates an ingestion job.

Request:

- multipart field `file`;
- optional `source_organization`;
- optional `topic_hint`;
- `Idempotency-Key` header.

Response `202 Accepted`:

```json
{
  "jobId": "ing_01K...",
  "datasetVersionId": "dsv_01K...",
  "status": "received",
  "links": {
    "job": "/api/v1/ingestion-jobs/ing_01K..."
  }
}
```

### `POST /api/v1/uploads`

Issues a short-lived presigned S3 form for the AWS runtime. The response contains
the server-generated `jobId`, the S3 `url` and signed `fields`, plus `complete`
and shared ingestion-job links. The browser submits the file as
`multipart/form-data`; the API server does not proxy the file bytes.

After S3 returns `204`, call:

```http
POST /api/v1/uploads/{jobId}/complete
Content-Type: application/json

{"objectKey": "incoming/{jobId}/...csv", "topicHint": "population"}
```

The completion endpoint verifies the object size, signed job metadata, submitter,
and key prefix before starting the Step Functions execution. It is safe to retry:
the Step Functions execution name is the same `jobId`.

An S3 notification routed through EventBridge may invoke
`adapters.aws.upload_event_handler.handler` instead. The event handler performs
the same verification and starts the same idempotently named execution, so the
callback and event paths can safely converge.

AWS configuration:

- `YOUTH_COMPASS_INCOMING_BUCKET`
- `YOUTH_COMPASS_STATE_MACHINE_ARN`
- `YOUTH_COMPASS_REGION` (defaults to `us-east-1`)

### `GET /api/v1/ingestion-jobs/{job_id}`

```json
{
  "jobId": "ing_01K...",
  "status": "awaiting_approval",
  "progress": 55,
  "currentStep": "mapping_validation",
  "qualityScore": 0.87,
  "createdAt": "2026-08-31T12:00:00Z",
  "updatedAt": "2026-08-31T12:00:08Z",
  "warnings": []
}
```

### `GET /api/v1/ingestion-jobs/{job_id}/mapping`

Returns source profile, mapping proposal, validation report, before/after samples, and integration recommendation.

### `POST /api/v1/ingestion-jobs/{job_id}/decision`

```json
{
  "decision": "approve",
  "mappingRevision": null,
  "comment": "Validated district aliases and unit"
}
```

Allowed decisions:

- `approve`;
- `approve_with_revision`;
- `reject`;
- `request_reprofile`.

### `GET /api/v1/ingestion-jobs/{job_id}/quality-report`

Returns quality dimensions, field-level issues, rejected-row summary, and publication eligibility.

## 4. Dataset catalog endpoints

### `GET /api/v1/datasets`

Filters:

- `topic`;
- `status`;
- `population_scope`;
- `period_start`;
- `period_end`.

### `GET /api/v1/datasets/{dataset_id}`

Returns current version, schema, grain, coverage, quality, limitations, and version links.

### `GET /api/v1/datasets/{dataset_id}/versions`

Returns immutable publication history.

### `GET /api/v1/datasets/{dataset_id}/lineage`

Returns source checksum, mapping, transformation, approval, and downstream derived assets.

## 5. Dashboard analytics endpoints

### `GET /api/v1/city/summary`

Parameters:

- `period`;
- optional `gender`.

Response includes youth population, historical change, number of declining districts, data freshness, and quality status.

### `GET /api/v1/districts`

Returns canonical district identifiers, names, and map-compatible metadata.

### `GET /api/v1/districts/{district_code}/profile`

Parameters:

- `period`;
- optional `gender`.

Response:

```json
{
  "district": {"code": "23", "name": "石門區"},
  "period": "2025-12",
  "metrics": [
    {
      "code": "youth_population",
      "value": 2174,
      "unit": "persons",
      "populationScope": "youth_specific",
      "isEstimated": false,
      "qualityStatus": "valid"
    }
  ],
  "limitations": [],
  "datasetVersions": ["dsv_..."]
}
```

### `GET /api/v1/districts/{district_code}/trend`

Parameters:

- `metric`;
- `start`;
- `end`;
- optional `gender`.

### `POST /api/v1/districts/compare`

```json
{
  "districtCodes": ["23", "17"],
  "metrics": ["youth_population"],
  "period": {"start": "2018-01", "end": "2025-12"}
}
```

### `GET /api/v1/policy/priority-ranking`

Parameters:

- `focus`;
- `period`;
- `limit`;
- optional `weights_profile`.

The response includes the transparent score components. The ranking is deterministic; the LLM only explains it.

## 6. Forecast endpoints

### `GET /api/v1/districts/{district_code}/forecast`

Parameters:

- `horizon`, default 12 and maximum configured;
- optional `model_version`;
- optional `gender`.

Response includes prediction intervals, backtest metrics, model version, data version, and warnings.

### `GET /api/v1/models/{model_version}`

Returns model card, training period, dataset version, metrics, approval status, and artifact metadata.

### `POST /api/v1/training-jobs`

Restricted command used by an authorized workflow or operator.

```json
{
  "target": "youth_population_monthly",
  "datasetVersion": "dsv_...",
  "reason": "new_complete_period"
}
```

## 7. Copilot endpoints

### `POST /api/v1/copilot/sessions`

Creates a session and returns a session identifier.

### `POST /api/v1/copilot/chat`

```json
{
  "sessionId": "ses_01K...",
  "message": "Compare Shimen and Linkou",
  "dashboardContext": {
    "selectedDistricts": ["23"],
    "period": {"start": "2018-01", "end": "2025-12"},
    "activeMetric": "youth_population",
    "activePanel": "forecast"
  }
}
```

Synchronous response uses the structured agent response described in `04-agentic-ai.md`.

### `GET /api/v1/copilot/sessions/{session_id}/events`

SSE event types:

```text
agent.started
agent.plan.updated
tool.started
tool.completed
agent.warning
agent.answer.delta
agent.completed
agent.failed
```

Internal model reasoning is never exposed. Events describe actions and evidence at a user-safe level.

## 8. Dashboard action contract

```json
{
  "type": "UPDATE_DASHBOARD",
  "actions": [
    {"action": "SELECT_DISTRICTS", "values": ["23", "17"]},
    {"action": "SET_METRIC", "value": "youth_population"},
    {"action": "SET_PERIOD", "value": {"start": "2018-01", "end": "2025-12"}},
    {"action": "OPEN_PANEL", "value": "forecast"}
  ]
}
```

The frontend validates action types and values before applying them.

## 9. Error envelope

```json
{
  "error": {
    "code": "MAPPING_REVIEW_REQUIRED",
    "message": "The metric unit could not be determined",
    "details": [
      {"field": "job_seekers", "reason": "unknown_unit"}
    ],
    "traceId": "trc_01K..."
  }
}
```

Recommended status codes:

| Code | Use |
|---:|---|
| 400 | Invalid request |
| 404 | Unknown resource |
| 409 | Invalid workflow state or duplicate publication |
| 413 | Upload too large |
| 422 | Schema or mapping validation failure |
| 429 | Rate or concurrency limit |
| 500 | Unexpected internal failure |
| 503 | Model/query provider unavailable |

## 10. Pagination and caching

- Dataset lists use cursor pagination.
- Large analytical results are rejected in favor of aggregate endpoints.
- Responses expose `ETag` or dataset-version-based cache keys.
- Forecasts and city summaries are precomputed and cacheable.
- A `dataset.published` event invalidates affected cache entries.

## 11. Local and AWS compatibility

FastAPI route handlers call application services only. They do not know whether the service is backed by DuckDB or Athena, filesystem or S3, local model or Bedrock. AWS deployment may preserve FastAPI in a container or wrap the same use cases with Lambda handlers.
