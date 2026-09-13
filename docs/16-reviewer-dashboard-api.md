# Reviewer and Dashboard API

> Status: offline reference and React reviewer workspace implemented
> Contract: `contracts/api/openapi.json`

## 1. Vertical slice

The API exposes one complete offline path:

```text
multipart CSV, Excel, JSON, or text-based PDF-table upload
  -> durable job + mapping review
  -> approve/reject endpoint
  -> curated or quarantined Parquet
  -> SQLite dataset catalog
  -> allowlisted DuckDB query
  -> dashboard summary/profile/compare response
```

Run it locally:

```bash
uv run uvicorn apps.api.main:app --reload
```

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

## 2. Implemented reviewer endpoints

| Method | Path | Result |
|---|---|---|
| POST | `/api/v1/datasets/upload` | Stores the original tabular source and returns an awaiting-review job |
| POST | `/api/v1/uploads` | Issues an AWS presigned multipart form with a stable ingestion `jobId` |
| POST | `/api/v1/uploads/{job_id}/complete` | Verifies S3 and idempotently starts Step Functions |
| GET | `/api/v1/ingestion-jobs/{job_id}` | Safe status, score, warnings, and links |
| GET | `/api/v1/ingestion-jobs/{job_id}/mapping` | Profile, proposal, and deterministic validation |
| GET | `/api/v1/ingestion-jobs/{job_id}/mapping-preview` | Up to three bounded before/after samples for each mapped column |
| POST | `/api/v1/ingestion-jobs/{job_id}/decision` | Approve or reject exactly once |
| GET | `/api/v1/ingestion-jobs/{job_id}/quality-report` | Quality result after transformation |

## 3. Implemented catalog and dashboard endpoints

| Method | Path | Result |
|---|---|---|
| GET | `/api/v1/datasets` | One visible version per dataset |
| GET | `/api/v1/datasets/{dataset_id}` | Current metadata without storage paths |
| GET | `/api/v1/datasets/{dataset_id}/versions` | Version history |
| GET | `/api/v1/datasets/{dataset_id}/lineage` | Checksum, mapping version, and approval |
| GET | `/api/v1/city/summary` | Latest or requested-period aggregate |
| GET | `/api/v1/districts` | All district aggregates for a metric and period |
| GET | `/api/v1/districts/{code}/profile` | One district aggregate |
| POST | `/api/v1/districts/compare` | Deterministic comparison for up to ten districts |

Every analytics response includes dataset/version, metric, unit, population scope,
quality score, and period. Estimated observations are reported separately.

## 4. React data-steward workflow

The main React application opens the reviewer workspace as soon as an upload or
approved source acquisition reaches `awaiting_approval`. It presents the source
profile, AI-proposed field and metric mappings, confidence badges, normalized
sample values, and blocking or advisory validation issues. The steward must
provide an identity and explicitly approve or reject the proposal; approval is
disabled when deterministic validation has a blocking issue.

The current job can also be reopened with `?review=<jobId>`. Only the job ID is
stored in the URL. The optional write token remains in React memory and is sent
only on upload, acquisition, and decision requests.

## 5. Query safety

`DuckDBQueryEngine` accepts only `QuerySpec`; no API accepts raw SQL. It validates:

- table against a non-empty allowlist;
- selected metrics and dimensions;
- filter fields;
- order-by fields;
- canonical identifier grammar;
- maximum returned rows.

Filter values use DuckDB parameters. The adapter reads only the Parquet path
resolved from the published catalog pointer. A missing, quarantined, or rejected
dataset cannot be queried by dashboard endpoints.

## 6. Public-data boundary

Responses intentionally omit:

- local source and Parquet paths;
- object-store URIs;
- callback tokens;
- raw rejected rows;
- arbitrary SQL or table names selected by an agent.

Errors use `{ "error": { "code", "message", "details", "traceId" } }`.
Unknown resources return 404, invalid workflow transitions return 409, and unsafe
or invalid analytics queries return 409/422.

## 7. Deferred dashboard API work

- authentication and reviewer authorization;
- upload idempotency-key records;
- pagination and ETags;
- city historical-change and priority-ranking marts;
- trend endpoint and cached pre-aggregations;
- SSE job progress;
- forecast and copilot routes.
