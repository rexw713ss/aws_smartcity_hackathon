# Data Directory

All project data lives under this directory. Existing cleaned datasets were moved without content changes into `source/`.

| Directory | Purpose | Git policy |
|---|---|---|
| `source/` | Existing provided datasets and lookup tables | Tracked, read-only input |
| `samples/` | Small tracked files for deterministic local demos | Tracked test input |
| `incoming/` | Newly uploaded files or API snapshots | Generated, ignored |
| `quarantined/` | Sources that fail or await review | Generated, ignored |
| `standardized/` | Source-shaped outputs with canonical dimensions | Generated, ignored |
| `curated/` | Approved analytical Parquet datasets | Generated, ignored |
| `forecasts/` | Batch forecast outputs | Generated, ignored |
| `metadata/` | Local catalog, quality reports, mappings, and audit state | Generated, ignored |

## Safety rules

- Do not modify files under `source/` in place.
- Every ingestion starts by preserving the original bytes in `incoming/`.
- Only approved and validated versions may be published to `curated/`.
- Generated directories are excluded from Git except for placeholder files.
- Cross-topic analysis must align time, geography, population scope, and grain before joining.

See [Data Architecture](../docs/02-data-architecture.md) and [Ingestion Workflow](../docs/03-ingestion-and-harmonization.md).
