# Real-Data Analytics Loop

> Owner: AWS integration engineer
> Status: **Implemented and verified live end to end on the hackathon account.**
> Audience: teammates who need to understand how an approved upload becomes queryable, and the application-layer engineer wiring analytics.

An approved upload is now transformed into canonical Parquet, registered as a typed Glue table, and served to the API through Athena — replacing the earlier behaviour where the workflow copied the raw CSV and registered a source-shaped table. This document records what the loop does, the least-privilege boundaries, and how it was verified.

---

## 1. The loop

```mermaid
flowchart LR
  U[Upload approved] --> T[Transform Lambda]
  T -->|run_csv_transformation| P[(canonical Parquet)]
  P -->|upload| C[(S3 curated/{dataset_id}/version={v}/part-000.parquet)]
  T -->|typed schema| G[(Glue table = dataset_id)]
  T -->|DatasetMetadata + pointer| D[(DynamoDB)]
  API[API Lambda] -->|catalog read| D
  API -->|Athena query| C
```

1. **Transform.** On the approved path the transform Lambda runs the same `run_csv_transformation` the local pipeline uses, producing canonical `CANONICAL_OBSERVATION_SCHEMA` Parquet (45 fields). Publish vs quarantine is decided by the transform's own quality gates — the manifest status — not the approval flag alone, so an approved-but-low-quality dataset is quarantined and never enters the catalog.
2. **Versioned layout.** The Parquet is uploaded to `curated/{dataset_id}/version={dataset_version}/part-000.parquet`. The version is content-addressed (source hash + mapping hash + transformation-version hash), so re-uploading the same file is idempotent — same version, one table.
3. **Glue.** The curated location is registered as an `EXTERNAL_TABLE` named by `dataset_id`, with the canonical columns typed from the Arrow schema (e.g. `year_gregorian smallint`, `metric_value double`, `is_estimated boolean`), a Parquet SerDe, and the dataset version in table parameters. A new version repoints the same table.
4. **Metadata.** `DatasetMetadata` plus a `__published__` pointer are written to DynamoDB in the shape the catalog reads, so the API resolves the published dataset.
5. **Serve.** With the AWS profile active the API reads the catalog from Glue+DynamoDB and runs analytics through Athena over the curated zone.

---

## 2. Athena workgroup

`DataStack` defines a workgroup (`{prefix}-analytics`) with results under `s3://{metadata-bucket}/athena-results/`. Its configuration is **enforced** (`enforce_work_group_configuration=True`) with a **1 GiB bytes-scanned cutoff per query**, so a caller cannot override the output location or raise the cap. The curated datasets are a few MB, so the cap is a runaway-query guardrail, not a working limit. CloudWatch metrics are on.

Names are exposed as stack outputs — `GlueDatabaseName`, `AthenaWorkGroupName`, `AthenaResultsUri`, `MetadataBucketName`, `CuratedBucketName` — and passed into the API stack, so nothing is hard-coded.

---

## 3. Least privilege

Only the ingestion workflow can publish curated data. The **API role is read-only for analytics**, verified with `iam simulate-principal-policy`:

| Action on curated | API role |
|---|---|
| `s3:GetObject` | allowed |
| `s3:PutObject` | denied |
| `s3:DeleteObject` | denied |

The API can run Athena queries in the one workgroup, read Glue schemas (`glue:Get*` scoped to the one database's tables — no `CreateTable`/`UpdateTable`/`DeleteTable`), and read/write only the `athena-results/` prefix of the metadata bucket.

---

## 4. Enabling the AWS analytics profile

The API stack sets these on the Lambda so the composition root selects Glue+Athena:

```
YOUTH_COMPASS_CATALOG__PROVIDER=glue
YOUTH_COMPASS_CATALOG__DATABASE=<glue database>
YOUTH_COMPASS_QUERY__PROVIDER=athena
YOUTH_COMPASS_QUERY__WORKGROUP=<workgroup>
YOUTH_COMPASS_ATHENA_RESULTS_BUCKET=<metadata bucket>
```

Offline (no profile) the API stays on SQLite + DuckDB. Both query engines enforce the same metric/dimension allowlist and the Athena engine is scoped to the one dataset's table, so analytics behaviour is identical across profiles.

Metric codes matter: query `/city/summary?datasetId=population&metricCode=population_count` — `population_count` is the dataset's `metric_code`, not the `metric_value` column.

---

## 5. Packaging

The transform Lambda now bundles `pyarrow` and `duckdb` (write + verify Parquet, duplicate-grain check) alongside `pydantic`, `openpyxl`, and `boto3`. `polars` is deliberately excluded — the transform reads CSV with the stdlib and writes with `pyarrow.parquet`, so it is not on the path. Measured **212 MB unzipped, 38 MB under the 250 MB limit**, so the zip route holds and no container image is needed. The build fails loudly if a change pushes it over.

---

## 6. Two bugs found by deploying

**`year_gregorian is not an integer` (HTTP 422).** Athena serialises every result cell as a string, but the `QueryEngine` contract returns native types and the analytics layer relies on that (the DuckDB engine returns typed values). The Athena adapter now coerces each cell using the column's declared Athena type, leaving an unparseable value as a string so one bad cell cannot fail a query.

**The confidence gate crashing a messy upload** — fixed earlier; recorded in `docs/21-api-deployment.md`.

---

## 7. Verified live

Against the hackathon account, not mocked:

- Population CSV uploaded via the presigned API → workflow `SUCCEEDED`
- Canonical Parquet at `curated/population/version=.../part-000.parquet` (9 observations, quality 1.0)
- Glue `population` table: Parquet SerDe, `year_gregorian smallint`, `metric_value double`, version in parameters
- Athena returned real 2023–2025 rows — 板橋區 47100/47800/48200, 新莊區 40230/41010/41720, 中和區 34900/35240/35580
- The API role can `GetObject` curated but is denied `PutObject`/`DeleteObject`
- Deployed dashboard endpoints over Athena: `/city/summary` (2025 total 125,500 across 3 districts), `/districts` (real per-district values), `/datasets` (Glue catalog lists `population`)

688 tests pass; `ruff` and `mypy --strict` clean.

---

## 8. What was intentionally not touched

Per the request, the agent response contract and decision-scoring logic were left alone. This work is the AWS analytics path only: transform, curated layout, Glue, Athena, and the API's read wiring.

## 9. Related documents

- `docs/21-api-deployment.md` — API and static-site deployment
- `docs/aws-workstream-status.md` — overall AWS status
- `docs/13-aws-stage2-adapters.md` — the adapter contracts
