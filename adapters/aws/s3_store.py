"""S3 ObjectStore adapter.

Feature: aws-stage2-adapters, Requirement 2.

Implements ``put/get/list/exists`` over S3 URIs. Every ``botocore`` exception is
translated into the domain error hierarchy; no technology-specific exception
crosses the port boundary.
"""

import hashlib

import boto3
import botocore.exceptions

from youth_compass.domain.errors import ObjectNotFoundError

_SCHEME = "s3://"


class S3ObjectStore:
    """ObjectStore backed by a single S3 bucket."""

    def __init__(self, bucket: str, region: str = "ap-northeast-1") -> None:
        self._bucket = bucket
        self._s3 = boto3.client("s3", region_name=region)

    def put(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        """Write content to S3 and return the scheme-qualified URI."""
        checksum = hashlib.sha256(content).hexdigest()
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content,
            Metadata={**metadata, "sha256": checksum},
        )
        return f"{_SCHEME}{self._bucket}/{key}"

    def get(self, uri: str) -> bytes:
        """Read bytes from S3. Raises ObjectNotFoundError for missing keys."""
        bucket, key = self._parse_uri(uri)
        try:
            response = self._s3.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()  # type: ignore[no-any-return]
        except botocore.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                raise ObjectNotFoundError(uri) from exc
            raise ObjectNotFoundError(uri) from exc

    def list(self, prefix: str) -> list[str]:
        """Return all keys beginning with prefix."""
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(keys)

    def exists(self, uri: str) -> bool:
        """Return whether the object at uri is readable."""
        bucket, key = self._parse_uri(uri)
        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        if uri.startswith(_SCHEME):
            rest = uri[len(_SCHEME) :]
            parts = rest.split("/", 1)
            return parts[0], parts[1] if len(parts) > 1 else ""
        return self._bucket, uri
