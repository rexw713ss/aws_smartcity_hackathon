"""S3/EventBridge entrypoint that starts ingestion for a completed upload."""

import os
from typing import Any
from urllib.parse import unquote_plus

from adapters.aws.s3_uploads import S3UploadSigner
from adapters.aws.step_functions_runner import StepFunctionsRunner
from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ports import IngestionRequest


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Verify one S3 object event and idempotently start Step Functions."""

    del context
    bucket, object_key = _event_object(event)
    configured_bucket = os.environ.get("YOUTH_COMPASS_INCOMING_BUCKET", bucket)
    if bucket != configured_bucket:
        raise WorkflowStateError(f"unexpected incoming bucket {bucket!r}")
    state_machine_arn = os.environ.get("YOUTH_COMPASS_STATE_MACHINE_ARN")
    if not state_machine_arn:
        raise WorkflowStateError("YOUTH_COMPASS_STATE_MACHINE_ARN is required")
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    job_id = _job_id_from_key(object_key)
    uploaded = S3UploadSigner(bucket=bucket, region=region).verify_upload(
        job_id=job_id,
        object_key=object_key,
    )
    reference = StepFunctionsRunner(
        state_machine_arn=state_machine_arn,
        region=region,
    ).start_ingestion(
        IngestionRequest(
            source_uri=uploaded.source_uri,
            submitted_by=uploaded.submitted_by,
            job_id=job_id,
            original_filename=uploaded.original_filename,
        )
    )
    return reference.model_dump(mode="json")


def _event_object(event: dict[str, Any]) -> tuple[str, str]:
    records = event.get("Records")
    if isinstance(records, list) and records:
        record = records[0]
        return (
            record["s3"]["bucket"]["name"],
            unquote_plus(record["s3"]["object"]["key"]),
        )
    detail = event.get("detail")
    if isinstance(detail, dict):
        try:
            return detail["bucket"]["name"], unquote_plus(detail["object"]["key"])
        except (KeyError, TypeError) as exc:
            raise WorkflowStateError("invalid EventBridge S3 event") from exc
    raise WorkflowStateError("unsupported S3 event shape")


def _job_id_from_key(object_key: str) -> str:
    parts = object_key.split("/")
    if len(parts) < 3 or parts[0] != "incoming" or not parts[1].startswith("job-"):
        raise WorkflowStateError(f"object key has no ingestion job id: {object_key!r}")
    return parts[1]
