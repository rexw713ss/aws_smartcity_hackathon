"""Public API models that never expose local infrastructure paths."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.analytics import (
    CitySummary,
    DistrictBreakdown,
    DistrictMetric,
    DistrictOverview,
    DistrictProfile,
    DistrictTrendPoint,
)
from youth_compass.domain.contracts import DatasetMetadata, QualityReport
from youth_compass.domain.types import FileFormat
from youth_compass.ports import JobStatus

#: The one reviewer-upload limit, shared by the upload route and the chat that
#: tells a reviewer about it before they pick a file.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class ErrorBody(ApiModel):
    code: str
    message: str
    details: list[dict[str, object]] = Field(default_factory=list)
    trace_id: str


class ErrorEnvelope(ApiModel):
    error: ErrorBody


class UploadResponse(ApiModel):
    job_id: str
    status: JobStatus
    links: dict[str, str]


class JobStatusResponse(ApiModel):
    job_id: str
    dataset_id: str | None = None
    status: JobStatus
    source_format: FileFormat | None = None
    current_step: str
    quality_score: float | None = None
    created_at: datetime
    warnings: list[str] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)


class DecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]
    decided_by: str = Field(min_length=1)
    comment: str | None = None


class DatasetResponse(ApiModel):
    dataset_id: str
    version: str
    topic: str
    status: str
    dataset_role: str
    grain: list[str]
    population_scope: str
    quality_score: float
    created_at: datetime
    published_at: datetime | None

    @classmethod
    def from_metadata(cls, metadata: DatasetMetadata) -> "DatasetResponse":
        return cls(
            dataset_id=metadata.dataset_id,
            version=metadata.version,
            topic=metadata.topic,
            status=metadata.status.value,
            dataset_role=metadata.dataset_role.value,
            grain=metadata.grain.dimensions,
            population_scope=metadata.population_scope.value,
            quality_score=metadata.quality_score,
            created_at=metadata.created_at,
            published_at=metadata.published_at,
        )


class LineageResponse(ApiModel):
    dataset_id: str
    dataset_version: str
    source_sha256: str
    mapping_version: str | None
    approved_by: str | None
    created_at: datetime
    published_at: datetime | None


class QualityResponse(ApiModel):
    job_id: str
    dataset_id: str
    dataset_version: str
    publication_status: str
    quality: QualityReport


class DistrictCompareRequest(ApiModel):
    dataset_id: str
    district_codes: list[str] = Field(min_length=1, max_length=10)
    metric_code: str
    period: str | None = None


class CitySummaryResponse(ApiModel):
    dataset_id: str
    dataset_version: str
    metric_code: str
    period: str
    value: float
    unit_code: str
    population_scope: str
    district_count: int
    estimated_value: float
    quality_score: float

    @classmethod
    def from_result(cls, result: CitySummary) -> "CitySummaryResponse":
        return cls.model_validate(result.model_dump())


class DistrictMetricResponse(ApiModel):
    district_code: str
    district_name: str | None
    value: float
    estimated_value: float

    @classmethod
    def from_result(cls, result: DistrictMetric) -> "DistrictMetricResponse":
        return cls.model_validate(result.model_dump())


class DistrictProfileResponse(ApiModel):
    dataset_id: str
    dataset_version: str
    metric_code: str
    period: str
    unit_code: str
    population_scope: str
    quality_score: float
    districts: list[DistrictMetricResponse]

    @classmethod
    def from_result(cls, result: DistrictProfile) -> "DistrictProfileResponse":
        payload = result.model_dump(exclude={"districts"})
        return cls(
            **payload,
            districts=[DistrictMetricResponse.from_result(item) for item in result.districts],
        )


class DistrictTrendPointResponse(ApiModel):
    period: str
    value: float

    @classmethod
    def from_result(cls, result: DistrictTrendPoint) -> "DistrictTrendPointResponse":
        return cls.model_validate(result.model_dump())


class DistrictBreakdownResponse(ApiModel):
    key: str
    label: str
    value: float
    share_percent: float

    @classmethod
    def from_result(cls, result: DistrictBreakdown) -> "DistrictBreakdownResponse":
        return cls.model_validate(result.model_dump())


class DistrictOverviewResponse(ApiModel):
    dataset_id: str
    dataset_version: str
    district_code: str
    district_name: str | None
    period: str
    unit_code: str
    population_scope: str
    quality_score: float
    total: float
    previous_period: str | None
    absolute_change: float | None
    percent_change: float | None
    trend: list[DistrictTrendPointResponse]
    age_distribution: list[DistrictBreakdownResponse]
    gender_distribution: list[DistrictBreakdownResponse]

    @classmethod
    def from_result(cls, result: DistrictOverview) -> "DistrictOverviewResponse":
        payload = result.model_dump(exclude={"trend", "age_distribution", "gender_distribution"})
        return cls(
            **payload,
            trend=[DistrictTrendPointResponse.from_result(item) for item in result.trend],
            age_distribution=[
                DistrictBreakdownResponse.from_result(item) for item in result.age_distribution
            ],
            gender_distribution=[
                DistrictBreakdownResponse.from_result(item) for item in result.gender_distribution
            ],
        )
