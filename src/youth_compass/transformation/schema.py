"""Stable Arrow schemas for canonical observations and row diagnostics."""

import pyarrow as pa  # type: ignore[import-untyped]

# Re-exported so this module stays the canonical place to look for the column
# order, while consumers that need only the names can avoid importing pyarrow.
from youth_compass.domain.canonical import CANONICAL_FIELDS

__all__ = [
    "CANONICAL_FIELDS",
    "CANONICAL_OBSERVATION_SCHEMA",
    "REJECTED_ROW_SCHEMA",
]

CANONICAL_OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("source_row_number", pa.int64(), nullable=False),
        pa.field("source_sha256", pa.string(), nullable=False),
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("dataset_version", pa.string(), nullable=False),
        pa.field("mapping_version", pa.string(), nullable=False),
        pa.field("transformation_version", pa.string(), nullable=False),
        pa.field("topic", pa.string(), nullable=False),
        pa.field("dataset_role", pa.string(), nullable=False),
        pa.field("year_roc", pa.int16()),
        pa.field("year_gregorian", pa.int16()),
        pa.field("month", pa.int8()),
        pa.field("period_start", pa.date32()),
        pa.field("period_granularity", pa.string(), nullable=False),
        pa.field("city_code", pa.string(), nullable=False),
        pa.field("city_name", pa.string(), nullable=False),
        pa.field("district_code", pa.string()),
        pa.field("district_name", pa.string()),
        pa.field("geography_granularity", pa.string(), nullable=False),
        pa.field("age_label_original", pa.string()),
        pa.field("age_lower", pa.int16()),
        pa.field("age_upper", pa.int16()),
        pa.field("youth_relationship", pa.string(), nullable=False),
        pa.field("youth_weight", pa.float64()),
        pa.field("is_estimated", pa.bool_(), nullable=False),
        pa.field("gender_code", pa.string()),
        pa.field("gender_label_original", pa.string()),
        pa.field("education_code", pa.string()),
        pa.field("education_order", pa.int16()),
        pa.field("graduation_status", pa.string()),
        pa.field("marital_status_code", pa.string()),
        pa.field("same_sex_marriage", pa.bool_()),
        pa.field("direction", pa.string()),
        pa.field("counterpart_region", pa.string()),
        pa.field("initial_registration_reason", pa.string()),
        pa.field("event_code", pa.string()),
        pa.field("marriage_type", pa.string()),
        pa.field("source_topic", pa.string()),
        pa.field("source_agency", pa.string()),
        pa.field("source_dataset_name", pa.string()),
        pa.field("metric_code", pa.string(), nullable=False),
        pa.field("metric_value", pa.float64(), nullable=False),
        pa.field("metric_value_original", pa.float64(), nullable=False),
        pa.field("unit_code", pa.string(), nullable=False),
        pa.field("aggregation_method", pa.string(), nullable=False),
        pa.field("population_scope", pa.string(), nullable=False),
    ]
)

REJECTED_ROW_SCHEMA = pa.schema(
    [
        pa.field("source_row_number", pa.int64(), nullable=False),
        pa.field("error_code", pa.string(), nullable=False),
        pa.field("field", pa.string()),
        pa.field("message", pa.string(), nullable=False),
    ]
)
