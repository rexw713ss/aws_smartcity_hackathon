"""FastAPI reviewer and dashboard API for the offline reference runtime."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.dependencies import LocalRuntime
from apps.api.schemas import (
    CitySummaryResponse,
    DatasetResponse,
    DecisionRequest,
    DistrictCompareRequest,
    DistrictProfileResponse,
    ErrorBody,
    ErrorEnvelope,
    JobStatusResponse,
    LineageResponse,
    QualityResponse,
    UploadResponse,
)
from apps.api.uploads import (
    aws_workflow_configured,
    get_aws_job_reference,
    resume_aws_job,
)
from apps.api.uploads import (
    router as uploads_router,
)
from youth_compass import __version__
from youth_compass.domain import (
    AnalyticsNotAvailableError,
    DatasetNotFoundError,
    QueryExecutionError,
    QueryNotPermittedError,
    SourceNormalizationError,
    WorkflowNotFoundError,
    WorkflowStateError,
    YouthCompassError,
)
from youth_compass.domain.contracts import MappingAnalysis
from youth_compass.ports import ApprovalDecision, JobReference

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def create_app(data_root: Path = Path("data")) -> FastAPI:
    app = FastAPI(title="New Taipei Youth Compass API", version=__version__)
    app.state.runtime = LocalRuntime(data_root)
    app.include_router(uploads_router)

    @app.exception_handler(YouthCompassError)
    async def domain_error_handler(request: Request, exc: YouthCompassError) -> JSONResponse:
        del request
        envelope = ErrorEnvelope(
            error=ErrorBody(
                code=_error_code(exc),
                message=str(exc),
                trace_id=f"trc_{uuid.uuid4().hex}",
            )
        )
        return JSONResponse(
            status_code=_status_for_error(exc),
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        details: list[dict[str, object]] = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "reason": error["msg"],
            }
            for error in exc.errors()
        ]
        envelope = ErrorEnvelope(
            error=ErrorBody(
                code="VALIDATION_FAILED",
                message="request validation failed",
                details=details,
                trace_id=f"trc_{uuid.uuid4().hex}",
            )
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post(
        "/api/v1/datasets/upload",
        response_model=UploadResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["reviewer"],
    )
    async def upload_dataset(
        request: Request,
        file: Annotated[UploadFile, File()],
        submitted_by: Annotated[str, Form()],
        topic_hint: Annotated[str | None, Form()] = None,
    ) -> UploadResponse:
        content = await file.read(_MAX_UPLOAD_BYTES + 1)
        if len(content) > _MAX_UPLOAD_BYTES:
            raise WorkflowStateError("upload exceeds the 25 MiB local limit")
        reference = _runtime(request).workflow.submit_bytes(
            file_name=file.filename or "",
            content=content,
            submitted_by=submitted_by,
            topic_hint=topic_hint,
        )
        return UploadResponse(
            job_id=reference.job_id,
            status=reference.status,
            links={"job": f"/api/v1/ingestion-jobs/{reference.job_id}"},
        )

    @app.get(
        "/api/v1/ingestion-jobs/{job_id}",
        response_model=JobStatusResponse,
        tags=["reviewer"],
    )
    def get_ingestion_job(job_id: str, request: Request) -> JobStatusResponse:
        try:
            return _job_response(_runtime(request), job_id)
        except WorkflowNotFoundError:
            if not aws_workflow_configured():
                raise
            return _aws_job_response(get_aws_job_reference(request, job_id))

    @app.get(
        "/api/v1/ingestion-jobs/{job_id}/mapping",
        response_model=MappingAnalysis,
        tags=["reviewer"],
    )
    def get_mapping(job_id: str, request: Request) -> MappingAnalysis:
        return _runtime(request).workflow.get_job(job_id).mapping_analysis

    @app.post(
        "/api/v1/ingestion-jobs/{job_id}/decision",
        response_model=JobStatusResponse,
        tags=["reviewer"],
    )
    def decide_ingestion(
        job_id: str, payload: DecisionRequest, request: Request
    ) -> JobStatusResponse:
        runtime = _runtime(request)
        decision = ApprovalDecision(
            approved=payload.decision == "approve",
            decided_by=payload.decided_by,
            decided_at=datetime.now(UTC),
            notes=payload.comment,
        )
        try:
            runtime.workflow.resume_after_approval(job_id, decision)
            return _job_response(runtime, job_id)
        except WorkflowNotFoundError:
            if not aws_workflow_configured():
                raise
            resume_aws_job(request, job_id, decision)
            return _aws_job_response(get_aws_job_reference(request, job_id))

    @app.get(
        "/api/v1/ingestion-jobs/{job_id}/quality-report",
        response_model=QualityResponse,
        tags=["reviewer"],
    )
    def get_quality_report(job_id: str, request: Request) -> QualityResponse:
        job = _runtime(request).workflow.get_job(job_id)
        if job.manifest is None:
            raise WorkflowStateError(f"quality report is not available while job is {job.status}")
        return QualityResponse(
            job_id=job.job_id,
            dataset_id=job.dataset_id,
            dataset_version=job.manifest.dataset_version,
            publication_status=job.manifest.status.value,
            quality=job.manifest.quality,
        )

    @app.get("/api/v1/datasets", response_model=list[DatasetResponse], tags=["catalog"])
    def list_datasets(request: Request) -> list[DatasetResponse]:
        return [
            DatasetResponse.from_metadata(metadata)
            for metadata in _runtime(request).catalog.list_datasets()
        ]

    @app.get(
        "/api/v1/datasets/{dataset_id}",
        response_model=DatasetResponse,
        tags=["catalog"],
    )
    def get_dataset(dataset_id: str, request: Request) -> DatasetResponse:
        return DatasetResponse.from_metadata(_runtime(request).catalog.get(dataset_id))

    @app.get(
        "/api/v1/datasets/{dataset_id}/versions",
        response_model=list[DatasetResponse],
        tags=["catalog"],
    )
    def get_dataset_versions(dataset_id: str, request: Request) -> list[DatasetResponse]:
        versions = _runtime(request).catalog.list_versions(dataset_id)
        if not versions:
            raise DatasetNotFoundError(dataset_id)
        return [DatasetResponse.from_metadata(metadata) for metadata in versions]

    @app.get(
        "/api/v1/datasets/{dataset_id}/lineage",
        response_model=LineageResponse,
        tags=["catalog"],
    )
    def get_lineage(dataset_id: str, request: Request) -> LineageResponse:
        metadata = _runtime(request).catalog.get(dataset_id)
        return LineageResponse(
            dataset_id=metadata.dataset_id,
            dataset_version=metadata.version,
            source_sha256=metadata.source_sha256,
            mapping_version=metadata.mapping_version,
            approved_by=metadata.approved_by,
            created_at=metadata.created_at,
            published_at=metadata.published_at,
        )

    @app.get(
        "/api/v1/city/summary",
        response_model=CitySummaryResponse,
        tags=["dashboard"],
    )
    def city_summary(
        request: Request,
        dataset_id: str = Query(..., alias="datasetId"),
        metric_code: str = Query(..., alias="metricCode"),
        period: str | None = Query(default=None),
    ) -> CitySummaryResponse:
        result = _runtime(request).analytics(dataset_id).city_summary(metric_code, period)
        return CitySummaryResponse.from_result(result)

    @app.get(
        "/api/v1/districts",
        response_model=DistrictProfileResponse,
        tags=["dashboard"],
    )
    def list_districts(
        request: Request,
        dataset_id: str = Query(..., alias="datasetId"),
        metric_code: str = Query(..., alias="metricCode"),
        period: str | None = Query(default=None),
    ) -> DistrictProfileResponse:
        result = (
            _runtime(request)
            .analytics(dataset_id)
            .district_profile(
                metric_code,
                period=period,
            )
        )
        return DistrictProfileResponse.from_result(result)

    @app.get(
        "/api/v1/districts/{district_code}/profile",
        response_model=DistrictProfileResponse,
        tags=["dashboard"],
    )
    def district_profile(
        district_code: str,
        request: Request,
        dataset_id: str = Query(..., alias="datasetId"),
        metric_code: str = Query(..., alias="metricCode"),
        period: str | None = Query(default=None),
    ) -> DistrictProfileResponse:
        result = (
            _runtime(request)
            .analytics(dataset_id)
            .district_profile(
                metric_code,
                district_codes=[district_code],
                period=period,
            )
        )
        return DistrictProfileResponse.from_result(result)

    @app.post(
        "/api/v1/districts/compare",
        response_model=DistrictProfileResponse,
        tags=["dashboard"],
    )
    def compare_districts(
        payload: DistrictCompareRequest, request: Request
    ) -> DistrictProfileResponse:
        result = (
            _runtime(request)
            .analytics(payload.dataset_id)
            .district_profile(
                payload.metric_code,
                district_codes=payload.district_codes,
                period=payload.period,
            )
        )
        return DistrictProfileResponse.from_result(result)

    return app


def _runtime(request: Request) -> LocalRuntime:
    runtime: LocalRuntime = request.app.state.runtime
    return runtime


def _job_response(runtime: LocalRuntime, job_id: str) -> JobStatusResponse:
    job = runtime.workflow.get_job(job_id)
    issues = [issue.message for issue in job.mapping_analysis.validation.issues]
    quality_score = (
        job.manifest.quality.quality_score if job.manifest else job.metadata.quality_score
    )
    return JobStatusResponse(
        job_id=job.job_id,
        dataset_id=job.dataset_id,
        status=job.status,
        source_format=job.source_format,
        current_step=job.status.value,
        quality_score=quality_score,
        created_at=job.metadata.created_at,
        warnings=[*job.source_warnings, *job.mapping_analysis.proposal.warnings, *issues],
        links={
            "mapping": f"/api/v1/ingestion-jobs/{job.job_id}/mapping",
            "quality": f"/api/v1/ingestion-jobs/{job.job_id}/quality-report",
        },
    )


def _aws_job_response(reference: JobReference) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=reference.job_id,
        status=reference.status,
        current_step=reference.status.value,
        created_at=reference.created_at,
        links={"job": f"/api/v1/ingestion-jobs/{reference.job_id}"},
    )


def _status_for_error(exc: YouthCompassError) -> int:
    if isinstance(exc, DatasetNotFoundError | AnalyticsNotAvailableError | WorkflowNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, WorkflowStateError | QueryNotPermittedError):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, QueryExecutionError):
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, SourceNormalizationError):
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _error_code(exc: YouthCompassError) -> str:
    name = type(exc).__name__.removesuffix("Error")
    snake = "".join(f"_{character}" if character.isupper() else character for character in name)
    return snake.upper().lstrip("_")


app = create_app()
