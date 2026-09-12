"""Canonical observation field names.

Kept separate from ``youth_compass.transformation.schema`` because that module
builds Arrow schemas and therefore imports pyarrow, the largest dependency in
the tree. Consumers that only need the *names* of the canonical fields — the
API's query allowlist, for example — import them from here instead, which keeps
pyarrow off the import path of read-only deployments such as the API packaged
for AWS Lambda.

``transformation.schema`` re-exports this tuple, so it remains the single source
of truth for the canonical column order.
"""

CANONICAL_FIELDS = (
    "source_row_number",
    "source_sha256",
    "dataset_id",
    "dataset_version",
    "mapping_version",
    "transformation_version",
    "topic",
    "dataset_role",
    "year_roc",
    "year_gregorian",
    "month",
    "period_start",
    "period_granularity",
    "city_code",
    "city_name",
    "district_code",
    "district_name",
    "geography_granularity",
    "age_label_original",
    "age_lower",
    "age_upper",
    "youth_relationship",
    "youth_weight",
    "is_estimated",
    "gender_code",
    "gender_label_original",
    "education_code",
    "education_order",
    "graduation_status",
    "marital_status_code",
    "same_sex_marriage",
    "direction",
    "counterpart_region",
    "initial_registration_reason",
    "event_code",
    "marriage_type",
    "source_topic",
    "source_agency",
    "source_dataset_name",
    "metric_code",
    "metric_value",
    "metric_value_original",
    "unit_code",
    "aggregation_method",
    "population_scope",
)
