"""Structured profiling results used by mapping and review workflows."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.domain.types import (
    FileFormat,
    PrimitiveType,
    SemanticRole,
    WarningSeverity,
)


class ProfileWarning(BaseModel):
    code: str
    message: str
    severity: WarningSeverity = WarningSeverity.WARNING
    field: str | None = None


class ColumnProfile(BaseModel):
    name: str
    position: int = Field(ge=0)
    inferred_type: PrimitiveType
    semantic_role: SemanticRole = SemanticRole.UNKNOWN
    semantic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    null_rate: float = Field(ge=0.0, le=1.0)
    distinct_count: int = Field(ge=0)
    distinct_count_is_lower_bound: bool = False
    sample_values: list[str] = Field(default_factory=list)
    numeric_min: float | None = None
    numeric_max: float | None = None


class TimeCoverage(BaseModel):
    year_gregorian_min: int | None = None
    year_gregorian_max: int | None = None
    source_year_system: str | None = None
    months: list[int] = Field(default_factory=list)
    months_by_gregorian_year: dict[int, list[int]] = Field(default_factory=dict)


class GeographyCoverage(BaseModel):
    district_count: int = Field(default=0, ge=0)
    recognized_district_count: int = Field(default=0, ge=0)
    unknown_values: list[str] = Field(default_factory=list)
    # Some rows describe the whole city rather than one district.
    city_level: bool = False


class DatasetProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_path: Path
    file_name: str
    file_format: FileFormat
    encoding: str
    delimiter: str
    file_size_bytes: int = Field(ge=0)
    content_sha256: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[ColumnProfile]
    candidate_grain: list[str] = Field(default_factory=list)
    duplicate_rows_checked: int = Field(default=0, ge=0)
    duplicate_row_count: int = Field(default=0, ge=0)
    duplicate_check_is_partial: bool = False
    time_coverage: TimeCoverage = TimeCoverage()
    geography_coverage: GeographyCoverage = GeographyCoverage()
    warnings: list[ProfileWarning] = Field(default_factory=list)
    truncated_by_max_rows: bool = False
