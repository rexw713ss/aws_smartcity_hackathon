"""S3 presigned-upload URL generation.

The browser uploads directly to S3 using a short-lived signed URL, so large
files never flow through the API server. Deliberately separate from the
ObjectStore port: presigned URLs are S3-specific and are not part of the
technology-agnostic port contract.

Security posture (docs/08 section 4.2):
- the server assigns a generated key; the client never chooses the S3 key;
- only an allowlisted set of content types is signed;
- a maximum object size is enforced by the signed policy;
- uploads always land under the ``incoming/`` prefix of the incoming bucket.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import boto3
import botocore.exceptions

from youth_compass.domain.errors import YouthCompassError

# Allowlisted upload content types and their canonical extension.
_ALLOWED_CONTENT_TYPES = {
    "text/csv": "csv",
    "application/vnd.ms-excel": "csv",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

_DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB
_DEFAULT_EXPIRY_SECONDS = 900  # 15 minutes
_MAX_SUBMITTED_BY_LENGTH = 256


class UploadNotPermittedError(YouthCompassError):
    """The requested upload violates a content-type or size policy."""


class UploadNotReadyError(YouthCompassError):
    """The expected S3 object has not arrived or failed verification."""


@dataclass(frozen=True)
class PresignedUpload:
    """A presigned POST the browser submits the file to."""

    url: str
    fields: dict[str, str]
    job_id: str
    object_key: str
    expires_at: datetime
    max_bytes: int


@dataclass(frozen=True)
class UploadedObject:
    """Verified upload metadata used to start an ingestion workflow."""

    source_uri: str
    submitted_by: str
    original_filename: str | None
    content_type: str
    size_bytes: int


class S3UploadSigner:
    """Issues presigned POST policies for direct-to-S3 browser uploads."""

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        *,
        prefix: str = "incoming/",
        max_bytes: int = _DEFAULT_MAX_BYTES,
        expiry_seconds: int = _DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix if prefix.endswith("/") else f"{prefix}/"
        self._max_bytes = max_bytes
        self._expiry = expiry_seconds
        self._s3 = boto3.client("s3", region_name=region)

    def presign_upload(
        self,
        *,
        content_type: str,
        submitted_by: str,
        original_filename: str | None = None,
        job_id: str | None = None,
    ) -> PresignedUpload:
        """Return a presigned POST for one upload.

        The server assigns the object key; the client cannot choose it. The
        signed policy caps the content type and size.

        Raises:
            UploadNotPermittedError: the content type is not allowlisted.
        """
        extension = _ALLOWED_CONTENT_TYPES.get(content_type)
        if extension is None:
            allowed = ", ".join(sorted(_ALLOWED_CONTENT_TYPES))
            raise UploadNotPermittedError(
                f"content type {content_type!r} is not allowed; permitted: {allowed}"
            )
        if (
            not submitted_by.strip()
            or len(submitted_by) > _MAX_SUBMITTED_BY_LENGTH
            or not submitted_by.isprintable()
        ):
            raise UploadNotPermittedError(
                "submitted_by must contain 1-256 printable characters"
            )

        correlation_id = job_id or f"job-{uuid.uuid4().hex}"
        if not correlation_id.startswith("job-") or not correlation_id.removeprefix(
            "job-"
        ).isalnum():
            raise UploadNotPermittedError("job_id must use the generated job-<id> format")

        # Generated key: never trust the client's filename for the S3 key. The
        # job prefix makes completion verifiable without server-local state.
        object_key = f"{self._prefix}{correlation_id}/{uuid.uuid4().hex}.{extension}"
        expires_at = datetime.now(UTC) + timedelta(seconds=self._expiry)

        # Provenance metadata must be part of the signed policy: S3 rejects any
        # form field not declared in the conditions. So build the fields and
        # matching conditions BEFORE signing, not after.
        fields: dict[str, str] = {
            "Content-Type": content_type,
            "x-amz-meta-submitted-by": submitted_by,
            "x-amz-meta-job-id": correlation_id,
        }
        if original_filename:
            fields["x-amz-meta-original-filename"] = _safe_filename(original_filename)

        conditions: list[object] = [
            {"Content-Type": content_type},
            ["content-length-range", 1, self._max_bytes],
            *[{key: value} for key, value in fields.items() if key != "Content-Type"],
        ]

        try:
            presigned = self._s3.generate_presigned_post(
                Bucket=self._bucket,
                Key=object_key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=self._expiry,
            )
        except botocore.exceptions.ClientError as exc:
            raise YouthCompassError(f"failed to presign upload: {exc}") from exc

        return PresignedUpload(
            url=presigned["url"],
            fields=presigned["fields"],
            job_id=correlation_id,
            object_key=object_key,
            expires_at=expires_at,
            max_bytes=self._max_bytes,
        )

    def verify_upload(self, *, job_id: str, object_key: str) -> UploadedObject:
        """Verify that the signed object exists and belongs to ``job_id``."""

        expected_prefix = f"{self._prefix}{job_id}/"
        if not object_key.startswith(expected_prefix):
            raise UploadNotPermittedError("object_key does not belong to this ingestion job")
        try:
            response = self._s3.head_object(Bucket=self._bucket, Key=object_key)
        except botocore.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise UploadNotReadyError("uploaded object is not available yet") from exc
            raise YouthCompassError(f"failed to inspect uploaded object: {exc}") from exc

        metadata = response.get("Metadata", {})
        if metadata.get("job-id") != job_id:
            raise UploadNotPermittedError("uploaded object has invalid job metadata")
        submitted_by = metadata.get("submitted-by", "")
        if not submitted_by:
            raise UploadNotPermittedError("uploaded object is missing submitter metadata")
        size_bytes = int(response.get("ContentLength", 0))
        if not 1 <= size_bytes <= self._max_bytes:
            raise UploadNotPermittedError("uploaded object violates the signed size policy")
        return UploadedObject(
            source_uri=f"s3://{self._bucket}/{object_key}",
            submitted_by=submitted_by,
            original_filename=metadata.get("original-filename"),
            content_type=str(response.get("ContentType", "application/octet-stream")),
            size_bytes=size_bytes,
        )


def _safe_filename(name: str) -> str:
    """Strip path separators and control characters from a client filename."""
    cleaned = name.replace("\\", "/").split("/")[-1]
    return "".join(ch for ch in cleaned if ch.isprintable())[:200]
