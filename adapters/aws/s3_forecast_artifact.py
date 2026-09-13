"""ForecastService adapter over a forecast artifact and model card published to S3.

Feature: youth population forecast (docs/31), phase 2.

The deployed API reads the same two files the offline generator writes, so a
new forecast is published by uploading them rather than by rebuilding the API
package. A warm process keeps one downloaded copy per artifact ETag and checks
the ETag again only after ``refresh_seconds``, so a forecast question costs no
S3 round trip in the common case.

Reading follows the generator's promotion order. The card is uploaded before
the artifact, so a reader may briefly hold a card newer than its artifact; the
local reader then finds mismatched versions and omits the evidence rather than
pairing old numbers with new evidence.
"""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
import botocore.exceptions

from youth_compass.domain.errors import ForecastNotAvailableError, TrainingRejectedError
from youth_compass.ports import ForecastRequest, ForecastResult, TrainingRequest, TrainingRun

if TYPE_CHECKING:
    from adapters.local.precomputed_forecast import PrecomputedParquetForecastService

ARTIFACT_NAME = "current.parquet"
MODEL_CARD_NAME = "model-card.json"
_MISSING = ("NoSuchKey", "404", "NotFound")


class S3ForecastArtifactService:
    """Serve the forecast published under ``s3://bucket/prefix``."""

    def __init__(
        self,
        bucket: str,
        prefix: str,
        cache_dir: Path,
        *,
        region: str = "us-east-1",
        refresh_seconds: int = 300,
        client: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._cache_dir = cache_dir
        self._refresh_seconds = refresh_seconds
        self._s3 = client if client is not None else boto3.client("s3", region_name=region)
        self._clock = clock
        self._lock = threading.Lock()
        self._etag: str | None = None
        self._checked_at: float | None = None
        self._reader: PrecomputedParquetForecastService | None = None

    def get_forecast(self, request: ForecastRequest) -> ForecastResult:
        return self._current_reader().get_forecast(request)

    def trigger_training(self, request: TrainingRequest) -> TrainingRun:
        del request
        raise TrainingRejectedError(
            "the S3 forecast adapter is read-only; run the offline forecast pipeline"
        )

    def _current_reader(self) -> "PrecomputedParquetForecastService":
        with self._lock:
            now = self._clock()
            if (
                self._reader is not None
                and self._checked_at is not None
                and now - self._checked_at < self._refresh_seconds
            ):
                return self._reader
            etag = self._head_etag()
            self._checked_at = now
            if self._reader is None or etag != self._etag:
                self._reader = self._download(etag)
                self._etag = etag
            return self._reader

    def _head_etag(self) -> str:
        try:
            response = self._s3.head_object(Bucket=self._bucket, Key=self._key(ARTIFACT_NAME))
        except botocore.exceptions.ClientError as exc:
            raise ForecastNotAvailableError(
                f"no published forecast artifact at s3://{self._bucket}/{self._key(ARTIFACT_NAME)}"
            ) from exc
        return str(response["ETag"]).strip('"')

    def _download(self, etag: str) -> "PrecomputedParquetForecastService":
        # Imported here so the workflow's Lambda package, which ships only the AWS
        # adapters, can import publish_forecast_to_s3 from this module.
        from adapters.local.precomputed_forecast import PrecomputedParquetForecastService

        directory = self._cache_dir / etag
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / ARTIFACT_NAME
        card = directory / MODEL_CARD_NAME
        try:
            # IfMatch pins the bytes to the ETag just checked, so a concurrent
            # upload cannot be cached under the previous version's name.
            response = self._s3.get_object(
                Bucket=self._bucket, Key=self._key(ARTIFACT_NAME), IfMatch=etag
            )
            artifact.write_bytes(response["Body"].read())
        except botocore.exceptions.ClientError as exc:
            raise ForecastNotAvailableError(
                "the published forecast artifact changed or vanished while it was read"
            ) from exc
        try:
            self._s3.download_file(self._bucket, self._key(MODEL_CARD_NAME), str(card))
        except botocore.exceptions.ClientError as exc:
            # A forecast without its card is still a valid forecast; it is served
            # without the backtest evidence rather than refused.
            if exc.response.get("Error", {}).get("Code", "") not in _MISSING:
                raise ForecastNotAvailableError(
                    "the forecast model card could not be read"
                ) from exc
            card.unlink(missing_ok=True)
        return PrecomputedParquetForecastService(artifact, model_card=card)

    def _key(self, name: str) -> str:
        return f"{self._prefix}{name}"


def publish_forecast_to_s3(
    artifact: Path,
    model_card: Path,
    *,
    bucket: str,
    prefix: str,
    client: Any | None = None,
    region: str = "us-east-1",
) -> tuple[str, str]:
    """Upload a validated card and artifact, card first, and return their URIs."""

    s3 = client if client is not None else boto3.client("s3", region_name=region)
    card_key = f"{prefix}{MODEL_CARD_NAME}"
    artifact_key = f"{prefix}{ARTIFACT_NAME}"
    s3.upload_file(str(model_card), bucket, card_key, ExtraArgs={"ContentType": "application/json"})
    s3.upload_file(
        str(artifact),
        bucket,
        artifact_key,
        ExtraArgs={"ContentType": "application/vnd.apache.parquet"},
    )
    return f"s3://{bucket}/{card_key}", f"s3://{bucket}/{artifact_key}"
