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
from datetime import UTC, datetime

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


class UploadNotPermittedError(YouthCompassError):
    """The requested upload violates a content-type or size policy."""


@dataclass(frozen=True)
class PresignedUpload:
    """A presigned POST the browser submits the file to."""

    url: str
    fields: dict[str, str]
    object_key: str
    expires_at: datetime
    max_bytes: int


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

        # Generated key: never trust the client's filename for the S3 key.
        object_key = f"{self._prefix}{uuid.uuid4().hex}.{extension}"
        expires_at = datetime.now(UTC)

        # Provenance metadata must be part of the signed policy: S3 rejects any
        # form field not declared in the conditions. So build the fields and
        # matching conditions BEFORE signing, not after.
        fields: dict[str, str] = {
            "Content-Type": content_type,
            "x-amz-meta-submitted-by": submitted_by,
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
            object_key=object_key,
            expires_at=expires_at,
            max_bytes=self._max_bytes,
        )


def _safe_filename(name: str) -> str:
    """Strip path separators and control characters from a client filename."""
    cleaned = name.replace("\\", "/").split("/")[-1]
    return "".join(ch for ch in cleaned if ch.isprintable())[:200]
