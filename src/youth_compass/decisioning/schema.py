"""Stable Parquet schema for materialized reusable feature values."""

import pyarrow as pa  # type: ignore[import-untyped]

FEATURE_VALUE_SCHEMA = pa.schema(
    [
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("feature_code", pa.string(), nullable=False),
        pa.field("feature_version", pa.string(), nullable=False),
        pa.field("feature_value", pa.float64(), nullable=False),
        pa.field("observed_at", pa.timestamp("us")),
        pa.field("quality_score", pa.float64(), nullable=False),
        pa.field("latest_retrieved_at", pa.timestamp("us"), nullable=False),
        pa.field("evidence_json", pa.string(), nullable=False),
    ]
)
