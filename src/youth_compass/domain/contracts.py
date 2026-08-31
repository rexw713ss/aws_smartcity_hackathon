"""Canonical contracts shared by ingestion, review, APIs, and adapters."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from youth_compass.domain.types import PrimitiveType, WarningSeverity


class PopulationScope(StrEnum):
    YOUTH_SPECIFIC = "youth_specific"
    DISTRICT_CONTEXT = "district_context"
    GENERAL_POPULATION = "general_population"
    UNKNOWN = "unknown"


class DatasetRole(StrEnum):
    FACT = "fact"
    CONTEXT = "context"
    DIMENSION = "dimension"
    UNKNOWN = "unknown"


class DatasetStatus(StrEnum):
    RECEIVED = "received"
    QUARANTINED = "quarantined"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHED = "published"
    REJECTED = "rejected"


class QualityStatus(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class CanonicalField(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    data_type: PrimitiveType
    required: bool = False
    aliases: list[str] = Field(default_factory=list)


class DatasetGrain(BaseModel):
    dimensions: list[str] = Field(min_length=1)

    @field_validator("dimensions")
    @classmethod
    def dimensions_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("grain dimensions must be unique")
        return value


class ColumnMapping(BaseModel):
    source_column: str
    target_field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    transformation: str
    transformation_parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class MetricMapping(BaseModel):
    source_column: str
    metric_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    unit_code: str | None = None
    population_scope: PopulationScope
    aggregation_method: str
    confidence: float = Field(ge=0.0, le=1.0)


class MappingProposal(BaseModel):
    topic: str
    dataset_role: DatasetRole
    grain: DatasetGrain
    columns: list[ColumnMapping] = Field(min_length=1)
    metrics: list[MetricMapping] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True


class QualityIssue(BaseModel):
    code: str
    message: str
    severity: WarningSeverity
    field: str | None = None
    row_count: int | None = Field(default=None, ge=0)
    blocking: bool = False


class QualityReport(BaseModel):
    status: QualityStatus
    quality_score: float = Field(ge=0.0, le=1.0)
    rows_received: int = Field(ge=0)
    rows_accepted: int = Field(ge=0)
    rows_rejected: int = Field(ge=0)
    issues: list[QualityIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def row_counts_must_be_consistent(self) -> Self:
        if self.rows_accepted + self.rows_rejected != self.rows_received:
            raise ValueError("accepted and rejected row counts must equal rows_received")
        return self


class DatasetMetadata(BaseModel):
    dataset_id: str
    version: str
    source_uri: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic: str
    dataset_role: DatasetRole
    grain: DatasetGrain
    population_scope: PopulationScope
    status: DatasetStatus
    quality_score: float = Field(ge=0.0, le=1.0)
    mapping_version: str | None = None
    approved_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None
