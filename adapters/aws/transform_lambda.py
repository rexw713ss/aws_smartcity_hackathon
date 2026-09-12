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

    The object is copied into the curated (approved) or quarantined (rejected)
    zone. On approval the curated location is additionally registered as a Glue
    table whose column schema is derived from the source profile, so the
    published data is immediately queryable through Athena. Rejected data is
    never registered, keeping quarantined rows out of the catalog.

    The heavy row-level transform is exercised by the local pipeline; here we
    prove the publish/quarantine branch, the curated-zone write, and the
    catalog registration.
    """
    import boto3

    approved = bool(event.get("approved", True))
    source_uri = event.get("source_uri", "")
    job_id = event.get("job_id", "unknown")
    if not source_uri.startswith("s3://"):
        raise YouthCompassError("transform requires an s3:// source_uri")
    _, _, rest = source_uri.partition("s3://")
    src_bucket, _, src_key = rest.partition("/")

    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    s3 = boto3.client("s3", region_name=region)
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

    result: dict[str, Any] = {
        "status": "ok",
        "action": "transform",
        "published": approved,
        "zone": zone,
        "uri": f"s3://{zone_bucket}/{dest_key}",
        "glue_table": None,
    }
    # Only published data enters the catalog; quarantined rows must stay out.
    if approved:
        result["glue_table"] = _register_curated_table(
            job_id=job_id,
            source=_download_from_s3(src_bucket, src_key),
            location=f"s3://{zone_bucket}/{zone}/{job_id}/",
            region=region,
        )
    return result


# PrimitiveType -> Hive/Glue column type. Glue has no "empty"; such a column
# carried no values to infer from, so the widest safe type is used.
_GLUE_COLUMN_TYPES = {
    "boolean": "boolean",
    "integer": "bigint",
    "float": "double",
    "date": "date",
    "string": "string",
    "empty": "string",
}


def _glue_identifier(value: str) -> str:
    """Reduce ``value`` to the lowercase alphanumeric/underscore Glue accepts."""
    cleaned = "".join(char if char.isalnum() else "_" for char in value.lower())
    stripped = cleaned.strip("_") or "dataset"
    # Glue rejects names starting with a digit in some engines; prefix if needed.
    return stripped if stripped[0].isalpha() else f"t_{stripped}"


def _register_curated_table(*, job_id: str, source: Path, location: str, region: str) -> str | None:
    """Create or update the Glue table describing the curated location.

    Returns the qualified ``database.table`` name, or ``None`` when no Glue
    database is configured (local and Moto runs that do not exercise Glue).
    """
    import boto3
    import botocore.exceptions

    database = os.environ.get("YOUTH_COMPASS_GLUE_DATABASE")
    if not database:
        return None

    profile = profile_csv(source)
    columns = [
        {
            "Name": _glue_identifier(column.name),
            "Type": _GLUE_COLUMN_TYPES.get(str(column.inferred_type), "string"),
        }
        for column in profile.columns
    ]
    table_name = _glue_identifier(job_id)
    table_input: dict[str, Any] = {
        "Name": table_name,
        "TableType": "EXTERNAL_TABLE",
        # skip.header.line.count keeps the CSV header row out of query results.
        "Parameters": {"classification": "csv", "skip.header.line.count": "1"},
        "StorageDescriptor": {
            "Columns": columns,
            "Location": location,
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                "Parameters": {"field.delim": ","},
            },
        },
    }

    glue = boto3.client("glue", region_name=region)
    try:
        glue.create_table(DatabaseName=database, TableInput=table_input)
    except botocore.exceptions.ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "AlreadyExistsException":
            raise
        # Re-publishing the same job replaces the schema rather than failing.
        glue.update_table(DatabaseName=database, TableInput=table_input)
    return f"{database}.{table_name}"


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
