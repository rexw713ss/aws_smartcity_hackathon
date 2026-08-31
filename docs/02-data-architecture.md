# Data Architecture

## 1. Objectives

The data layer must make heterogeneous public datasets comparable without hiding their differences. It must preserve original values, document every transformation, and prevent invalid joins caused by incompatible grains.

The architecture uses four logical zones:

```text
incoming -> quarantined -> standardized -> curated
```

| Zone | Purpose | Mutability |
|---|---|---|
| `incoming` | Original uploaded files and API snapshots | Immutable |
| `quarantined` | Sources awaiting review or failing validation | Versioned |
| `standardized` | Source-shaped data with canonical dimensions added | Rebuildable |
| `curated` | Approved analytical fact/dimension tables | Versioned publication |

Forecasts, metadata, and quality reports live in separate versioned namespaces.

## 2. Canonical dimensions

### 2.1 Time

| Field | Type | Description |
|---|---|---|
| `year_roc` | integer, nullable | Original or normalized Republic of China year |
| `year_gregorian` | integer | Gregorian year used internally |
| `month` | integer, nullable | 1-12; null for annual data |
| `period_start` | date | Normalized period start |
| `period_granularity` | enum | `month`, `year`, `unknown` |

Conversion rule:

```text
year_gregorian = year_roc + 1911
```

Original year strings must be retained in source lineage when parsing is ambiguous.

### 2.2 Geography

| Field | Type | Description |
|---|---|---|
| `city_code` | string | Canonical city code |
| `city_name` | string | Canonical city name |
| `district_code` | string | Stable district identifier |
| `district_name` | string | Canonical district name |
| `village_name` | string, nullable | Village-level label when present |
| `geography_granularity` | enum | `city`, `district`, `village`, `unknown` |

Aliases such as `板橋`, `板橋區`, and `新北市板橋區` map to the same district identifier. The alias dictionary must be versioned.

### 2.3 Age and youth relationship

| Field | Type | Description |
|---|---|---|
| `age_label_original` | string, nullable | Source label |
| `age_lower` | integer, nullable | Inclusive lower bound |
| `age_upper` | integer, nullable | Inclusive upper bound |
| `youth_relationship` | enum | `fully_within`, `partially_overlaps`, `unrelated`, `no_age_dimension`, `undefined` |
| `youth_weight` | decimal | Share of the age interval overlapping 18-35 |
| `is_estimated` | boolean | True when weighting or imputation is used |

For a bounded age interval, the default overlap is:

```text
overlap_count = max(0, min(age_upper, 35) - max(age_lower, 18) + 1)
interval_count = age_upper - age_lower + 1
youth_weight = overlap_count / interval_count
```

This assumes a uniform distribution within the interval. That assumption must be displayed whenever weighted values are used.

### 2.4 Demographic categories

| Field | Type | Description |
|---|---|---|
| `gender_code` | enum/string | Canonical value such as `male`, `female`, `other`, `unknown` |
| `gender_label_original` | string | Source value |
| `education_code` | string, nullable | Canonical education category |
| `marital_status_code` | string, nullable | Canonical marriage category |

Canonical categories do not erase original labels. Both values are retained for auditability.

## 3. Metric model

Every quantitative observation is described by:

| Field | Type | Description |
|---|---|---|
| `metric_code` | string | Stable machine-readable name |
| `metric_name` | string | Human-readable name |
| `metric_value` | decimal | Numeric value |
| `unit_code` | string | `persons`, `households`, `thousand_ntd`, `percent`, etc. |
| `aggregation_method` | enum | `sum`, `mean`, `median`, `ratio`, `not_additive` |
| `population_scope` | enum | `youth_specific`, `district_context`, `general_population`, `unknown` |

`population_scope` is critical. Income and migration sources without an age dimension must never be labeled as youth-specific.

## 4. Curated tables

### 4.1 `fact_youth_population_monthly`

Grain:

```text
year_gregorian x month x district_code x gender_code
```

Primary metrics:

- `youth_population_exact`;
- optional age-band detail in a separate table if needed.

Source data contains single-year ages, so the 18-35 total is exact rather than weighted.

### 4.2 `fact_youth_education_annual`

Grain:

```text
year_gregorian x district_code x gender_code x education_code
```

Values may be weighted when source bands cross 18 or 35. The output records `is_estimated=true` and retains the applied weight.

### 4.3 `fact_youth_marriage_annual`

Grain:

```text
year_gregorian x district_code x gender_code x marital_status_code
```

### 4.4 `fact_youth_events_annual`

Grain:

```text
year_gregorian x district_code x gender_code x event_code x education_code x marriage_type
```

The current repository should be treated as marriage-event data until divorce rows are proven to exist.

### 4.5 `context_district_income_annual`

Grain:

```text
year_gregorian x district_code [x village_name]
```

Income is district context, not youth income. The current source requires schema deduplication and district reconstruction before publication.

### 4.6 `context_district_migration_monthly`

Grain:

```text
year_gregorian x month x district_code x gender_code x direction x counterpart_region
```

Migration has no age dimension in the current source and remains contextual.

### 4.7 `fact_generic_metric`

Used only for new topics that do not yet justify a dedicated wide table:

```text
dataset_version x period x geography x demographic dimensions x metric_code
```

Promotion to a dedicated fact table occurs when a topic has stable semantics and repeated use.

## 5. Metadata contract

Each dataset version stores:

```json
{
  "datasetId": "employment_seekers",
  "version": "2026-08-31T120000Z",
  "sourceUri": "incoming/employment_115.csv",
  "sourceOrganization": "example-agency",
  "topic": "employment",
  "format": "csv",
  "grain": ["year", "district", "gender", "age_group"],
  "timeSystem": "roc",
  "periodGranularity": "year",
  "geographyGranularity": "district",
  "ageDefinition": "source_groups",
  "youthDefinition": "18-35-inclusive",
  "populationScope": "youth_specific",
  "qualityScore": 0.92,
  "mappingVersion": "mapping-v1",
  "status": "published",
  "approvedBy": "user-id",
  "publishedAt": "2026-08-31T12:10:00Z"
}
```

Metadata must also contain schema fingerprint, content checksum, row count, accepted/rejected rows, and lineage to transformation code versions.

## 6. Safe join policy

A join recommendation is valid only if:

1. common dimensions have the same semantic definition;
2. time and geography can be transformed to the same granularity;
3. metric units are compatible;
4. one side is unique on the proposed join key, or both sides are aggregated first;
5. age-specific and general-population scopes are not confused;
6. the resulting relationship is documented as correlation/context unless causal evidence exists.

### Example: safe

Annual education and monthly population may be compared after population is aggregated to:

```text
year x district x gender
```

### Example: unsafe

Joining raw age-by-sex population rows directly with education-by-age-by-marriage rows on only year and district produces a many-to-many expansion and must be rejected.

## 7. Partitioning

Recommended local and S3-compatible layout:

```text
data/curated/
  fact_youth_population_monthly/
    version=2026-08-31T120000Z/
      year=2025/
        part-000.parquet
```

Partition first by table/version and then by year. Avoid excessive district partitions because small files increase query overhead.

## 8. Dataset versioning and publication

- Raw content is addressed by checksum and never overwritten.
- Standardized outputs are reproducible from raw content, mapping version, and transformation version.
- Curated versions are immutable.
- A catalog pointer identifies the currently published version.
- Rollback changes the pointer rather than deleting data.
- Forecast output records the exact curated version used for training.

## 9. Existing repository risks to resolve

- Root topic documentation lists only the generic dataset despite nine topic directories.
- Population is missing ROC year 106 and ROC year 115 is partial.
- Migration ROC year 113 has incomplete month coverage.
- Income data contains parallel schemas and missing district fields in later years.
- Marriage-event metadata claims marriage and divorce while current rows expose marriage only.
- The generic open-data collection contains undefined fields and missing years.

These sources remain input evidence. They should not be copied directly into curated tables without explicit remediation rules and regression tests.
