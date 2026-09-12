# Athena-backed Agent observations

> Status: application wiring, query guardrails, CDK workgroup, and tests implemented.
> Live activation waits for the ingestion workflow to publish canonical Parquet metadata.

## Runtime path

For generic dataset inspection and trend/comparison questions, the AWS composition root uses:

```text
Agent -> ObservationToolSuite -> GlueCatalog published pointer
      -> typed QuerySpec -> AthenaQueryEngine -> canonical Parquet on S3
      -> deterministic comparison -> citation -> AnswerComposer/VisualizationBuilder
```

Decision ranking remains on the immutable feature snapshot, and the existing dashboard analytics
remain on DuckDB. This isolates the migration to generic Agent observations.

## Publication contract required from ingestion

For each published dataset, the metadata DynamoDB table must contain:

- one version item keyed by `dataset_id` and `version`, with `metadata_json` containing a valid
  `DatasetMetadata` whose status is `published` and whose `source_uri` points to the immutable
  canonical Parquet artifact;
- one pointer item keyed by the same `dataset_id` and `version=__published__`, with
  `published_version` selecting that immutable version;
- a Glue table named exactly as `dataset_id`, in the configured database, exposing the canonical
  fields from `youth_compass.domain.canonical`, including numeric `metric_value`.

Non-published records must never advance the pointer. Until this contract exists, the Agent fails
closed with insufficient data rather than querying an arbitrary Glue table.

## Runtime configuration

The Lambda receives these settings from CDK:

```text
YOUTH_COMPASS_CATALOG__PROVIDER=glue
YOUTH_COMPASS_CATALOG__DATABASE=<glue database>
YOUTH_COMPASS_CATALOG__TABLE_NAME=<metadata DynamoDB table>
YOUTH_COMPASS_QUERY__PROVIDER=athena
YOUTH_COMPASS_QUERY__WORKGROUP=<cost-capped workgroup>
YOUTH_COMPASS_QUERY__OUTPUT_BUCKET=<metadata bucket>
```

The workgroup enforces a 100 MiB scanned-bytes cutoff. The adapter separately enforces table,
metric, dimension, filter, and order-by allowlists; strict identifier syntax; escaped literals;
bounded pagination; typed result parsing; timeout cancellation; and a truthful truncation flag.

## Activation acceptance test

1. Publish the canonical population dataset through the approval-gated workflow.
2. Verify the version item, `__published__` pointer, Glue table, and Parquet location.
3. Deploy the API stack with the settings above.
4. Ask `Compare population trend from 2023 to 2025` for at least two district IDs.
5. Verify `query_observations` is `ok`, the citation names the new dataset version, and the line,
   comparison-bar, and table visualizations contain Athena-derived values.

