# Local Ingestion Workflow

> Status: implemented in `feature/local-ingestion-workflow`
> Purpose: provide the offline reference behavior that AWS adapters must preserve.

## 1. Outcome

The local workflow accepts a previously unseen CSV, stores the original bytes,
profiles and maps it deterministically, pauses for a human decision, and only then
transforms and publishes versioned Parquet. It runs without network access, an
LLM, or AWS credentials.

```text
CSV
  -> FileSystemObjectStore
  -> profile + mapping validation
  -> SQLite checkpoint: awaiting_approval
  -> human approve/reject
  -> deterministic transformation
  -> quality gate
  -> curated | quarantined
  -> SQLite catalog + published pointer
```

## 2. Components

| Component | Responsibility | Future AWS replacement |
|---|---|---|
| `FileSystemObjectStore` | Original bytes, arbitrary logical keys, checksum verification | S3 adapter |
| `SQLiteCatalog` | Dataset versions and atomic published pointer | Glue + DynamoDB adapter |
| `SQLiteCheckpointStore` | Latest job state and append-only transition history | Step Functions + durable state |
| `SystemClock` | Timezone-aware UTC timestamps | Same port or AWS runtime clock |
| `LocalIngestionWorkflow` | Business sequence and approval boundary | Reused application use case |
| `run_csv_transformation` | Deterministic CSV-to-Parquet transformation | Reused by Lambda/container worker |

Application code depends only on Protocols under `youth_compass.ports`. It does
not import SQLite, filesystem, boto3, or CDK types.

## 3. Durable state

The default CLI stores runtime artifacts below `data/`:

```text
data/
├── incoming/
│   ├── index.sqlite3
│   └── objects/
├── metadata/
│   └── youth-compass.sqlite3
├── curated/<dataset>/version=<version>/
└── quarantined/<dataset>/version=<version>/
```

The object index separates logical keys from host filesystem filenames. This
allows long keys and prevents path traversal from becoming filesystem traversal.
Every read verifies the stored SHA-256 checksum.

The metadata database contains:

- `dataset_versions`: one validated metadata document per dataset version;
- `published_versions`: one live pointer per dataset;
- `workflow_checkpoints`: latest state for status/resume;
- `workflow_history`: append-only transition snapshots.

## 4. State and publication rules

- A valid new mapping stops at `awaiting_approval` and writes no curated output.
- A blocking mapping is quarantined before an approval token is issued.
- A rejection is terminal and cannot be approved later.
- Mapping overrides fail closed until a validated override contract exists.
- An approval runs the deterministic transformation and quality checks.
- Quality failure produces a quarantined version but never changes the live pointer.
- Only metadata with status `published` advances `published_versions`.
- Replaying the same approved source reuses its immutable transformation version.

The output directory is atomically moved into place before the catalog pointer is
updated. If a process stops between those steps, retry reuses the verified output
and idempotently updates the catalog.

## 5. Operator workflow

Submit:

```bash
uv run youth-compass-local submit <source.csv> \
  --submitted-by <operator>
```

Review the returned job after any process restart:

```bash
uv run youth-compass-local status <job-id>
```

Settle exactly once:

```bash
uv run youth-compass-local decide <job-id> \
  --approve \
  --decided-by <reviewer>
```

Use `--reject` instead of `--approve` to reject. The status payload includes the
profile, mapping proposal, deterministic validation, reviewer decision, final
metadata, and publication manifest when transformation ran.

## 6. AWS integration contract

AWS orchestration should invoke the same application behavior rather than call
profiling and mapping functions independently. Infrastructure may replace storage,
catalog, checkpoints, and clock through their ports, but must preserve these
observable rules:

1. original bytes exist before parsing;
2. validation precedes approval;
3. transformation cannot run without a valid human decision;
4. quarantine/rejection cannot move the published pointer;
5. retry is idempotent;
6. the source URI and checksum survive into lineage metadata;
7. process restart does not lose approval state or audit history.

Known AWS implementation gaps and their acceptance criteria are tracked in
[`14-aws-integration-review.md`](./14-aws-integration-review.md).

## 7. Deferred work

- Reviewer REST endpoints and dashboard interface.
- Validated mapping override schema and revalidation flow.
- Authentication and authorization of uploader/reviewer identities.
- EventBus publication and cache invalidation.
- DuckDB view registration and analytical APIs.
