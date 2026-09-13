"""Deterministic canonical transformation and local Parquet publication.

Pipeline exports are loaded lazily so callers that only need lightweight value
preview helpers do not have to import the optional PyArrow runtime.
"""

from typing import TYPE_CHECKING, Any

from youth_compass.transformation.values import RowTransformationError, preview_column_value

if TYPE_CHECKING:
    from youth_compass.transformation.pipeline import (
        PublicationConflictError,
        TransformationError,
        TransformOptions,
    )

__all__ = [
    "PublicationConflictError",
    "RowTransformationError",
    "TransformOptions",
    "TransformationError",
    "preview_column_value",
    "run_csv_transformation",
]


def __getattr__(name: str) -> Any:
    """Load Parquet-backed pipeline exports only when they are requested."""

    if name in {
        "PublicationConflictError",
        "TransformationError",
        "TransformOptions",
        "run_csv_transformation",
    }:
        from youth_compass.transformation import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
