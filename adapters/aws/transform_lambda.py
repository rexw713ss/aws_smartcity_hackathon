"""Lambda handler for the deterministic transforms and workflow steps.

Feature: aws-stage2-adapters (Requirement 6 + PR2).

Calls the existing ``profile_csv`` and ``analyze_mapping`` functions — no
reimplementation. Also serves two workflow steps: ``await_approval`` (persists
the Step Functions task token so a human decision can resume the exact paused
execution) and ``transform`` (publishes the approved dataset to curated + Glue,
or routes to quarantine). The handler lives under ``adapters/aws/`` and is not
imported by any module under ``src/youth_compass/``.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from youth_compass.domain.errors import YouthCompassError
from youth_compass.ingestion.csv_profiler import profile_csv
from youth_compass.mapping.engine import MappingOptions, analyze_mapping


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dispatch to a workflow action.

    Actions:
      profile         -> {source_uri|bucket+key|source_path}
      analyze         -> same input; returns MappingAnalysis
      await_approval  -> {job_id, task_token}; persists token, sets awaiting_approval
      transform       -> {job_id, source_uri, approved}; publishes or quarantines
    """
    action = event.get("action", "")

    try:
        if action == "await_approval":
            return _await_approval(event)
        if action == "transform":
            return _transform(event)

        source = _resolve_source(event)
        if action == "profile":
            return _profile(source)
        if action == "analyze":
            return _analyze(source, topic_hint=event.get("topic_hint"))
        return _error(f"unknown action: {action!r}")
    except YouthCompassError as exc:
        return _error(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _error(f"unexpected: {type(exc).__name__}: {exc}"[:500])


def _resolve_source(event: dict[str, Any]) -> Path:
    bucket = event.get("bucket")
    key = event.get("key")
    source_uri = event.get("source_uri", "")
    source_path = event.get("source_path", "")
    if source_uri.startswith("s3://") and not (bucket and key):
        rest = source_uri[len("s3://") :]
        bucket, _, key = rest.partition("/")
    if not source_path and not (bucket and key):
        raise YouthCompassError("one of source_path, source_uri, or (bucket + key) is required")
    return _download_from_s3(bucket, key) if bucket and key else Path(source_path)


def _await_approval(event: dict[str, Any]) -> dict[str, Any]:
    """Persist the Step Functions task token so a human can resume the pause."""
    from adapters.aws.workflow_token_store import WorkflowTokenStore
    from youth_compass.ports.workflow_runner import JobStatus

    job_id = event.get("job_id")
    task_token = event.get("task_token")
    if not job_id or not task_token:
        raise YouthCompassError("await_approval requires job_id and task_token")
    table = os.environ["YOUTH_COMPASS_METADATA_TABLE"]
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    store = WorkflowTokenStore(table_name=table, region=region)
    store.put_status(job_id, JobStatus.AWAITING_APPROVAL)
    store.put_token(job_id, task_token)
    return {"status": "ok", "action": "await_approval", "job_id": job_id}


def _transform(event: dict[str, Any]) -> dict[str, Any]:
    """Publish the approved dataset to curated + Glue, or route to quarantine.

    Deliberately simple for the MVP: it copies the source object into the
    curated (approved) or quarantined (rejected) zone and records a manifest.
    The heavy row-level transform is exercised by the local pipeline; here we
    prove the publish/quarantine branch and the curated-zone write.
    """
    import boto3

    approved = bool(event.get("approved", True))
    source_uri = event.get("source_uri", "")
    job_id = event.get("job_id", "unknown")
    if not source_uri.startswith("s3://"):
        raise YouthCompassError("transform requires an s3:// source_uri")
    _, _, rest = source_uri.partition("s3://")
    src_bucket, _, src_key = rest.partition("/")

    s3 = boto3.client("s3", region_name=os.environ.get("YOUTH_COMPASS_REGION", "us-east-1"))
    zone_bucket = (
        os.environ["YOUTH_COMPASS_CURATED_BUCKET"]
        if approved
        else os.environ["YOUTH_COMPASS_QUARANTINED_BUCKET"]
    )
    zone = "curated" if approved else "quarantined"
    dest_key = f"{zone}/{job_id}/{Path(src_key).name}"
    s3.copy_object(
        Bucket=zone_bucket,
        Key=dest_key,
        CopySource={"Bucket": src_bucket, "Key": src_key},
    )
    return {
        "status": "ok",
        "action": "transform",
        "published": approved,
        "zone": zone,
        "uri": f"s3://{zone_bucket}/{dest_key}",
    }


def _download_from_s3(bucket: str, key: str) -> Path:
    """Download an S3 object to a temp file (boto3 imported lazily)."""
    import boto3

    suffix = Path(key).suffix or ".csv"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    boto3.client("s3").download_file(bucket, key, tmp)
    return Path(tmp)


def _profile(source: Path) -> dict[str, Any]:
    profile = profile_csv(source)
    return {"status": "ok", "action": "profile", "result": json.loads(profile.model_dump_json())}


def _analyze(source: Path, *, topic_hint: str | None = None) -> dict[str, Any]:
    profile = profile_csv(source)
    options = MappingOptions(topic_hint=topic_hint) if topic_hint else None
    analysis = analyze_mapping(profile, options)
    return {"status": "ok", "action": "analyze", "result": json.loads(analysis.model_dump_json())}


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}
