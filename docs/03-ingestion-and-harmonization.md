# Ingestion and Harmonization

## 1. Purpose

The onboarding workflow converts an unknown source into an approved, queryable dataset while preserving source fidelity and requiring review for ambiguous decisions.

## 2. Supported source maturity

| Source type | MVP | Later |
|---|---:|---:|
| CSV | Full | Full |
| XLSX | Optional | Full |
| JSON/API snapshot | Optional | Full |
| Native PDF table | No | Full |
| Scanned PDF | No | Textract/OCR workflow |
| Live scheduled API | No | EventBridge scheduled connector |

## 3. Job lifecycle

```text
received
  -> profiling
  -> mapping_proposed
  -> validating
  -> awaiting_approval | auto_approved | rejected
  -> transforming
  -> quality_check
  -> publishing | quarantined
  -> published | failed
```

Transitions are append-only audit events. A job cannot skip validation or publication checks.

## 4. Detailed workflow

### 4.1 Receive

- Generate `job_id` and `dataset_version_id`.
- Save original bytes before parsing.
- Compute SHA-256 checksum.
- Record filename, media type, size, uploader, and received timestamp.
- Reject unsupported size or type according to configuration.
- Detect repeated upload by checksum without deleting the new audit event.

### 4.2 Detect and parse

- Detect delimiter, encoding, header row, and quoting behavior.
- Preserve original column names exactly.
- Sample rows without loading the entire file into the LLM prompt.
- Parse into an internal tabular representation.
- Capture malformed rows rather than silently dropping them.

### 4.3 Profile

For every column calculate:

- inferred primitive type;
- null count and rate;
- distinct count;
- min/max for numeric and date-like values;
- representative values;
- candidate semantic roles;
- potential personally identifiable information warning;
- candidate unit based on header and values.

For the dataset calculate:

- row count;
- candidate primary keys;
- duplicate rate;
- period and geography coverage;
- likely topic;
- possible totals mixed with detail rows;
- schema fingerprint.

### 4.4 Retrieve canonical context

The system retrieves only relevant catalog context:

- canonical field definitions;
- alias dictionaries;
- existing topic schemas;
- transformation registry;
- known grains;
- compatible datasets;
- previous mappings for the same source organization.

### 4.5 Propose mapping

The schema mapper returns structured output:

```json
{
  "topic": "employment",
  "datasetRole": "fact",
  "grain": ["year", "district", "gender", "age_group"],
  "columns": [
    {
      "sourceColumn": "stat_year",
      "targetField": "year_roc",
      "transformation": "parse_year",
      "confidence": 0.99,
      "evidence": "Header stat_year matches the canonical alias registry"
    }
  ],
  "metrics": [
    {
      "sourceColumn": "job_seekers",
      "metricCode": "job_seekers",
      "unitCode": "persons",
      "populationScope": "youth_specific",
      "aggregationMethod": "sum",
      "confidence": 0.95,
      "evidence": "Header job_seekers matches the known metric registry"
    }
  ],
  "overallConfidence": 0.98,
  "warnings": [],
  "requiresHumanApproval": true
}
```

### 4.6 Deterministic validation

Validation checks the proposal against data rather than trusting model confidence:

- requested transformation exists in the allowlist;
- target field accepts the inferred source type;
- ROC year conversion falls in a configured range;
- district aliases resolve to valid districts;
- gender values resolve or remain explicitly unknown;
- age bounds are internally consistent;
- metric values and units are plausible;
- candidate grain is unique after known total rows are removed;
- join recommendation passes safe join policy.

Validation recalculates an evidence-based confidence score. LLM confidence is only one input.

### 4.7 Approval decision

Suggested default thresholds:

| Condition | Outcome |
|---|---|
| All required fields valid and score >= 0.95 | Auto-approve only when policy allows |
| Score 0.75-0.95 or any material warning | Human review |
| Score < 0.75, unknown unit, or unsafe grain | Quarantine/reject |

For the hackathon MVP, all newly introduced topics should require approval even with high confidence. This makes the safety boundary visible in the demo.

### 4.8 Transform

Transformation runs only registered functions:

```text
parse_roc_year
normalize_district
normalize_gender
parse_age_range
calculate_youth_overlap
normalize_unit
remove_verified_total_rows
cast_numeric
```

Every output row retains:

- source row number;
- source dataset version;
- mapping version;
- transformation version;
- estimation flag;
- rejection reason when applicable.

### 4.9 Quality check

Quality dimensions:

| Dimension | Example checks |
|---|---|
| Completeness | Missing required fields, missing months, district coverage |
| Validity | Allowed codes, ranges, numeric types, non-negative counts |
| Uniqueness | Duplicate candidate keys |
| Consistency | Unit and calendar consistency, matching totals |
| Timeliness | Latest available period and expected update cadence |
| Lineage | Source, mapping, transformation, approval fields present |

Example report:

```json
{
  "status": "needs_review",
  "qualityScore": 0.87,
  "rowsReceived": 1200,
  "rowsAccepted": 1176,
  "rowsRejected": 24,
  "duplicateRows": 12,
  "unknownDistrictValues": ["板橋"],
  "missingPeriods": ["2026-07"],
  "warnings": [
    "Age group 15-19 uses a 0.4 youth overlap estimate"
  ]
}
```

### 4.10 Recommend integration

The system returns one of:

- `append_existing_table`;
- `publish_new_topic_table`;
- `publish_context_table`;
- `manual_modeling_required`;
- `reject_incompatible_source`.

It also returns the required aggregation and join keys. A recommendation does not execute a cross-domain merge until approved.

### 4.11 Publish

- Write versioned Parquet output.
- Verify row count and schema by reopening the output.
- Register metadata and views.
- Atomically move the published-version pointer.
- Emit `dataset.published` event.
- Invalidate affected caches.
- Evaluate whether insight refresh or model retraining is required.

## 5. Retraining decision

Not every source triggers SageMaker/local training.

```text
Is the source part of the model feature/target contract?
  No -> refresh dashboard insights only
  Yes
    -> Did the published period advance or historical values materially change?
       No -> no retraining
       Yes
         -> quality threshold passed?
            No -> retain current model and flag data
            Yes -> schedule training pipeline
```

## 6. Idempotency

- Upload checksum identifies identical bytes.
- Job commands use idempotency keys.
- Publishing the same dataset version twice is a no-op.
- Transformation output path includes source checksum and mapping version.
- Retry does not create duplicate catalog entries.

## 7. Error handling

| Error | Behavior |
|---|---|
| Parser failure | Quarantine original file with parse diagnostics |
| Mapping validation failure | Return field-level errors for review |
| Transformation row errors | Capture rejected rows and continue if threshold permits |
| Excessive rejection rate | Fail publication |
| Catalog failure | Keep version unpublished and retry safely |
| Insight refresh failure | Preserve published data and flag stale derived views |
| Training failure | Preserve previous approved model and forecast |

## 8. Held-out validation files

The test suite must contain files that were not used to author specific mapping rules:

1. English headers and ROC years.
2. Traditional Chinese headers and Gregorian years.
3. `M/F` gender values.
4. district names with city prefix and without `區` suffix.
5. 15-19 and 35-39 boundary age bands.
6. duplicate rows and mixed total/detail rows.
7. missing metric unit.
8. a new topic that must become district context rather than youth-specific data.

## 9. Human review UI requirements

The review screen shows:

- original column and samples;
- proposed canonical field;
- proposed transformation;
- confidence and evidence;
- validation errors;
- before/after sample values;
- detected grain;
- proposed integration action;
- quality score impact;
- approve, edit, reject, and re-run actions.

Approval records user identity, timestamp, mapping diff, and justification when overriding a warning.
