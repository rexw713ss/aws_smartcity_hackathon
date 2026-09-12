"""Upload API: issue presigned S3 POST URLs for direct-to-bucket browser uploads.

The frontend calls ``POST /api/v1/uploads`` to get a short-lived signed form,
then submits the returned fields and file to S3 as ``multipart/form-data``.
The file never flows through this API server. The server assigns the object
key; the client cannot choose it.

Configuration comes from environment variables so this router adds no coupling
to the backend's settings loader:
- ``YOUTH_COMPASS_INCOMING_BUCKET``  (required for real uploads)
- ``YOUTH_COMPASS_REGION``           (default: us-east-1)
"""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field

from adapters.aws.s3_uploads import (
    S3UploadSigner,
    UploadNotPermittedError,
    UploadNotReadyError,
)
from adapters.aws.step_functions_runner import StepFunctionsRunner
from adapters.aws.workflow_token_store import WorkflowTokenStore
from apps.api.schemas import ApiModel
from youth_compass.domain.errors import YouthCompassError
from youth_compass.ports import (
    ApprovalDecision,
    IngestionRequest,
    JobReference,
    JobStatus,
    WorkflowRunner,
)

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


class UploadRequest(ApiModel):
    """A request for a presigned upload URL."""

    content_type: str = Field(examples=["text/csv"])
    submitted_by: str = Field(
        min_length=1,
        max_length=256,
        examples=["steward@ntpc.gov.tw"],
    )
    original_filename: str | None = Field(default=None, examples=["employment_2024.csv"])


class UploadResponse(ApiModel):
    """A presigned POST the browser submits the file to."""

    url: str
    fields: dict[str, str]
    job_id: str
    object_key: str
    status: JobStatus
    expires_at: datetime
    max_bytes: int
    links: dict[str, str]


class CompleteUploadRequest(ApiModel):
    """The browser callback after the multipart form succeeds."""

    object_key: str = Field(min_length=1)
    topic_hint: str | None = Field(default=None, max_length=100)


class StartedIngestionResponse(ApiModel):
    """Portable reference to the workflow started for an uploaded object."""

    job_id: str
    status: JobStatus
    created_at: datetime
    links: dict[str, str]


def _signer(request: Request) -> S3UploadSigner:
    bucket = os.environ.get("YOUTH_COMPASS_INCOMING_BUCKET")
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="upload storage is not configured (YOUTH_COMPASS_INCOMING_BUCKET unset)",
        )
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    cache_key = (bucket, region)
    cached = getattr(request.app.state, "s3_upload_signer", None)
    if cached is None or cached[0] != cache_key:
        cached = (cache_key, S3UploadSigner(bucket=bucket, region=region))
        request.app.state.s3_upload_signer = cached
    return cached[1]


def _runner(request: Request) -> WorkflowRunner:
    state_machine_arn = os.environ.get("YOUTH_COMPASS_STATE_MACHINE_ARN")
    if not state_machine_arn:
        raise HTTPException(
            status_code=503,
            detail="ingestion workflow is not configured (YOUTH_COMPASS_STATE_MACHINE_ARN unset)",
        )
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    metadata_table = os.environ.get("YOUTH_COMPASS_METADATA_TABLE")
    cache_key = (state_machine_arn, region, metadata_table)
    cached = getattr(request.app.state, "aws_workflow_runner", None)
    if cached is None or cached[0] != cache_key:
        # A durable token store makes approval state survive API/Lambda restarts
        # (PR2). Without a configured table the runner falls back to in-process
        # state, which is only appropriate for local development.
        token_store = (
            WorkflowTokenStore(table_name=metadata_table, region=region) if metadata_table else None
        )
        cached = (
            cache_key,
            StepFunctionsRunner(
                state_machine_arn=state_machine_arn,
                region=region,
                token_store=token_store,
            ),
        )
        request.app.state.aws_workflow_runner = cached
    return cached[1]


@router.post("", response_model=UploadResponse)
def create_upload(payload: UploadRequest, request: Request) -> UploadResponse:
    """Issue a presigned POST for one file upload into the incoming zone."""
    signer = _signer(request)
    job_id = f"job-{uuid.uuid4().hex}"
    try:
        presigned = signer.presign_upload(
            content_type=payload.content_type,
            submitted_by=payload.submitted_by,
            original_filename=payload.original_filename,
            job_id=job_id,
        )
    except UploadNotPermittedError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except YouthCompassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return UploadResponse(
        url=presigned.url,
        fields=presigned.fields,
        job_id=presigned.job_id,
        object_key=presigned.object_key,
        status=JobStatus.PENDING,
        expires_at=presigned.expires_at,
        max_bytes=presigned.max_bytes,
        links={
            "complete": f"/api/v1/uploads/{presigned.job_id}/complete",
            "job": f"/api/v1/ingestion-jobs/{presigned.job_id}",
        },
    )


@router.post(
    "/{job_id}/complete",
    response_model=StartedIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def complete_upload(
    job_id: str,
    payload: CompleteUploadRequest,
    request: Request,
) -> StartedIngestionResponse:
    """Verify the S3 object and start one idempotently named workflow."""

    try:
        uploaded = _signer(request).verify_upload(
            job_id=job_id,
            object_key=payload.object_key,
        )
        reference = _runner(request).start_ingestion(
            IngestionRequest(
                source_uri=uploaded.source_uri,
                submitted_by=uploaded.submitted_by,
                topic_hint=payload.topic_hint,
                job_id=job_id,
                original_filename=uploaded.original_filename,
            )
        )
    except UploadNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UploadNotPermittedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except YouthCompassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _started_response(reference)


def get_aws_job_reference(request: Request, job_id: str) -> JobReference:
    """Read an AWS-backed job for the shared ingestion status endpoint."""

    return _runner(request).get_job_reference(job_id)


def aws_workflow_configured() -> bool:
    """Return whether status fallback to Step Functions is available."""

    return bool(os.environ.get("YOUTH_COMPASS_STATE_MACHINE_ARN"))


def resume_aws_job(request: Request, job_id: str, decision: ApprovalDecision) -> None:
    """Resume an AWS-backed job from the shared review endpoint."""

    _runner(request).resume_after_approval(job_id, decision)


def _started_response(reference: JobReference) -> StartedIngestionResponse:
    return StartedIngestionResponse(
        job_id=reference.job_id,
        status=reference.status,
        created_at=reference.created_at,
        links={"job": f"/api/v1/ingestion-jobs/{reference.job_id}"},
    )
