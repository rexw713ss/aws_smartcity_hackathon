"""Upload API: issue presigned S3 POST URLs for direct-to-bucket browser uploads.

The frontend calls ``POST /uploads`` to get a short-lived signed URL, then PUTs
the file straight to S3. The file never flows through this API server. The
server assigns the object key; the client cannot choose it.

Configuration comes from environment variables so this router adds no coupling
to the backend's settings loader:
- ``YOUTH_COMPASS_INCOMING_BUCKET``  (required for real uploads)
- ``YOUTH_COMPASS_REGION``           (default: us-east-1)
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from adapters.aws.s3_uploads import S3UploadSigner, UploadNotPermittedError
from youth_compass.domain.errors import YouthCompassError

router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadRequest(BaseModel):
    """A request for a presigned upload URL."""

    content_type: str = Field(examples=["text/csv"])
    submitted_by: str = Field(min_length=1, examples=["steward@ntpc.gov.tw"])
    original_filename: str | None = Field(default=None, examples=["employment_2024.csv"])


class UploadResponse(BaseModel):
    """A presigned POST the browser submits the file to."""

    url: str
    fields: dict[str, str]
    object_key: str
    max_bytes: int


def _signer() -> S3UploadSigner:
    bucket = os.environ.get("YOUTH_COMPASS_INCOMING_BUCKET")
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="upload storage is not configured (YOUTH_COMPASS_INCOMING_BUCKET unset)",
        )
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    return S3UploadSigner(bucket=bucket, region=region)


@router.post("", response_model=UploadResponse)
def create_upload(request: UploadRequest) -> UploadResponse:
    """Issue a presigned POST for one file upload into the incoming zone."""
    signer = _signer()
    try:
        presigned = signer.presign_upload(
            content_type=request.content_type,
            submitted_by=request.submitted_by,
            original_filename=request.original_filename,
        )
    except UploadNotPermittedError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except YouthCompassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return UploadResponse(
        url=presigned.url,
        fields=presigned.fields,
        object_key=presigned.object_key,
        max_bytes=presigned.max_bytes,
    )
