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
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from youth_compass.domain.errors import YouthCompassError
from youth_compass.ingestion.csv_profiler import profile_csv
from youth_compass.mapping.engine import MappingOptions, analyze_mapping

if TYPE_CHECKING:
    from youth_compass.domain.contracts import (
        MappingProposal,
        PopulationScope,
        PublicationManifest,
    )

logger = logging.getLogger("youth_compass.transform_lambda")
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dispatch to a workflow action.

    Actions:
      profile         -> {source_uri|bucket+key|source_path}
      analyze         -> same input; returns MappingAnalysis
      await_approval  -> {job_id, task_token}; persists token, sets awaiting_approval
      transform       -> {job_id, source_uri, approved}; publishes or quarantines
    """
    action = event.get("action", "")
    job_id = event.get("job_id", "unknown")
    logger.info("transform_lambda start action=%s job_id=%s", action, job_id)

    try:
        if action == "await_approval":
            return _await_approval(event)
        if action == "transform":
            result = _transform(event)
            logger.info(
                "transform done job_id=%s published=%s dataset=%s version=%s glue=%s",
                job_id,
                result.get("published"),
                result.get("dataset_id"),
                result.get("dataset_version"),
                result.get("glue_table"),
            )
            return result

        source = _resolve_source(event)
        if action == "profile":
            return _profile(source)
        if action == "analyze":
            return _analyze(source, topic_hint=event.get("topic_hint"))
        return _error(f"unknown action: {action!r}")
    except YouthCompassError as exc:
        # Expected, translated failures: quality gate, missing config, bad source.
        logger.warning("transform_lambda action=%s job_id=%s failed: %s", action, job_id, exc)
        return _error(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        # Unexpected: log with a stack trace so CloudWatch has the detail, but
        # still return a structured error so Step Functions can route it.
        logger.exception("transform_lambda action=%s job_id=%s crashed", action, job_id)
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
    """Run the real canonical transform and publish versioned Parquet, or quarantine.

    The approved source is transformed into canonical observations by the same
    ``run_csv_transformation`` the local pipeline uses, written as Parquet under
    the canonical ``CANONICAL_OBSERVATION_SCHEMA``. The output object is uploaded
    to the versioned curated layout

        curated/{dataset_id}/version={dataset_version}/part-000.parquet

    and the curated location is registered as a typed Glue table so Athena can
    query it. Whether the result publishes or quarantines is decided by the
    transform's own quality gates (via the manifest status), not by the approval
    flag alone: an approved-but-low-quality dataset is quarantined and never
    enters the catalog.
    """
    import boto3

    approved = bool(event.get("approved", True))
    source_uri = event.get("source_uri", "")
    job_id = event.get("job_id", "unknown")
    reviewer = event.get("decided_by") or event.get("submitted_by") or "workflow"
    if not source_uri.startswith("s3://"):
        raise YouthCompassError("transform requires an s3:// source_uri")
    _, _, rest = source_uri.partition("s3://")
    src_bucket, _, src_key = rest.partition("/")

    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")
    curated_bucket = os.environ["YOUTH_COMPASS_CURATED_BUCKET"]
    quarantined_bucket = os.environ["YOUTH_COMPASS_QUARANTINED_BUCKET"]

    # A rejection decision short-circuits the transform: quarantine the raw
    # source and register nothing.
    if not approved:
        return _quarantine_source(
            src_bucket=src_bucket,
            src_key=src_key,
            job_id=job_id,
            bucket=quarantined_bucket,
            region=region,
        )

    from youth_compass.domain.contracts import PublicationStatus

    manifest, proposal = _run_canonical_transform(
        src_bucket=src_bucket,
        src_key=src_key,
        source_uri=source_uri,
        reviewer=reviewer,
        region=region,
    )

    published = manifest.status == PublicationStatus.PUBLISHED
    zone_bucket = curated_bucket if published else quarantined_bucket
    zone = "curated" if published else "quarantined"
    version_prefix = f"{zone}/{manifest.dataset_id}/version={manifest.dataset_version}"
    parquet_key = f"{version_prefix}/part-000.parquet"

    s3 = boto3.client("s3", region_name=region)
    s3.upload_file(manifest.parquet_uri, zone_bucket, parquet_key)

    result: dict[str, Any] = {
        "status": "ok",
        "action": "transform",
        "published": published,
        "zone": zone,
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "uri": f"s3://{zone_bucket}/{parquet_key}",
        "observation_count": manifest.observation_count,
        "rows_received": manifest.rows_received,
        "rows_rejected": manifest.rows_rejected,
        "quality_score": manifest.quality.quality_score,
        "glue_table": None,
    }
    # Only published data enters the catalog; quarantined rows must stay out.
    if published:
        result["glue_table"] = _register_curated_table(
            manifest=manifest,
            location=f"s3://{zone_bucket}/{version_prefix}/",
            region=region,
        )
        _register_dataset_metadata(manifest=manifest, proposal=proposal, region=region)
    return result


def _run_canonical_transform(
    *,
    src_bucket: str,
    src_key: str,
    source_uri: str,
    reviewer: str,
    region: str,
) -> "tuple[PublicationManifest, MappingProposal]":
    """Download the source, transform it, and return the manifest and mapping.

    Imported lazily: ``run_csv_transformation`` pulls in polars and pyarrow,
    which are only on the transform action's path, not profile/analyze. The
    proposal is re-derived from the source so the published dataset's grain,
    role, and scope can be recorded in metadata alongside the manifest.
    """
    from youth_compass.transformation import (
        TransformationError,
        TransformOptions,
        run_csv_transformation,
    )

    source = _download_from_s3(src_bucket, src_key)
    # Lambda's filesystem is read-only outside /tmp; the transform stages and
    # publishes under a curated/quarantine root, so both live in /tmp.
    work_root = Path(tempfile.mkdtemp(prefix="transform-", dir="/tmp"))
    try:
        manifest = run_csv_transformation(
            source,
            TransformOptions(
                approved_by=reviewer,
                curated_root=work_root / "curated",
                quarantine_root=work_root / "quarantined",
                source_uri=source_uri,
            ),
        )
    except TransformationError as exc:
        raise YouthCompassError(f"transformation failed: {exc}") from exc
    analysis = analyze_mapping(profile_csv(source))
    return manifest, analysis.proposal


def _quarantine_source(
    *,
    src_bucket: str,
    src_key: str,
    job_id: str,
    bucket: str,
    region: str,
) -> dict[str, Any]:
    """Copy a rejected source into quarantine unchanged; register nothing."""
    import boto3

    dest_key = f"quarantined/{job_id}/{Path(src_key).name}"
    boto3.client("s3", region_name=region).copy_object(
        Bucket=bucket,
        Key=dest_key,
        CopySource={"Bucket": src_bucket, "Key": src_key},
    )
    return {
        "status": "ok",
        "action": "transform",
        "published": False,
        "zone": "quarantined",
        "uri": f"s3://{bucket}/{dest_key}",
        "glue_table": None,
    }


# Arrow type string -> Hive/Glue column type for the canonical Parquet schema.
_ARROW_TO_GLUE = {
    "int8": "tinyint",
    "int16": "smallint",
    "int32": "int",
    "int64": "bigint",
    "float": "float",
    "double": "double",
    "bool": "boolean",
    "string": "string",
    "date32[day]": "date",
    "date64[ms]": "date",
}


def _glue_identifier(value: str) -> str:
    """Reduce ``value`` to the lowercase alphanumeric/underscore Glue accepts."""
    cleaned = "".join(char if char.isalnum() else "_" for char in value.lower())
    stripped = cleaned.strip("_") or "dataset"
    # Glue rejects names starting with a digit in some engines; prefix if needed.
    return stripped if stripped[0].isalpha() else f"t_{stripped}"


def _canonical_glue_columns() -> list[dict[str, str]]:
    """The 45 canonical fields as Glue columns, typed from the Arrow schema."""
    from youth_compass.transformation.schema import CANONICAL_OBSERVATION_SCHEMA

    columns: list[dict[str, str]] = []
    for field in CANONICAL_OBSERVATION_SCHEMA:
        arrow_type = str(field.type)
        glue_type = _ARROW_TO_GLUE.get(arrow_type)
        if glue_type is None:  # pragma: no cover - guards a schema change
            raise YouthCompassError(
                f"no Glue type mapping for Arrow type {arrow_type!r} (field {field.name!r})"
            )
        columns.append({"Name": field.name, "Type": glue_type})
    return columns


def _register_curated_table(
    *, manifest: "PublicationManifest", location: str, region: str
) -> str | None:
    """Create or update the Glue table for a published canonical dataset.

    The table carries the canonical column schema, a Parquet SerDe, the
    version-prefixed S3 location, and the dataset version in its parameters.
    Returns the qualified ``database.table`` name, or ``None`` when no Glue
    database is configured (local and Moto runs that do not exercise Glue).
    """
    import boto3
    import botocore.exceptions

    database = os.environ.get("YOUTH_COMPASS_GLUE_DATABASE")
    if not database:
        return None

    table_name = _glue_identifier(manifest.dataset_id)
    table_input: dict[str, Any] = {
        "Name": table_name,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {
            "classification": "parquet",
            "youth_compass_dataset_id": manifest.dataset_id,
            "youth_compass_dataset_version": manifest.dataset_version,
            "youth_compass_mapping_version": manifest.mapping_version,
        },
        "StorageDescriptor": {
            "Columns": _canonical_glue_columns(),
            "Location": location,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": ("org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"),
            "SerdeInfo": {
                "SerializationLibrary": (
                    "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                ),
            },
        },
    }

    glue = boto3.client("glue", region_name=region)
    try:
        glue.create_table(DatabaseName=database, TableInput=table_input)
    except botocore.exceptions.ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "AlreadyExistsException":
            logger.error("glue registration failed table=%s: %s", table_name, exc)
            raise YouthCompassError(f"glue table registration failed: {exc}") from exc
        # A new version of an existing dataset repoints the same table.
        glue.update_table(DatabaseName=database, TableInput=table_input)
    logger.info("glue table registered %s.%s at %s", database, table_name, location)
    return f"{database}.{table_name}"


def _register_dataset_metadata(
    *, manifest: "PublicationManifest", proposal: "MappingProposal", region: str
) -> None:
    """Persist DatasetMetadata + a published-version pointer in DynamoDB.

    Writes the same item shape ``GlueCatalog.get`` reads, so the deployed API's
    catalog lookup resolves this published dataset. Skipped when no metadata
    table is configured (local and Moto runs that do not exercise it).
    """
    import boto3

    from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus

    table_name = os.environ.get("YOUTH_COMPASS_METADATA_TABLE")
    if not table_name:
        return

    metadata = DatasetMetadata(
        dataset_id=manifest.dataset_id,
        version=manifest.dataset_version,
        source_uri=manifest.source_uri,
        source_sha256=manifest.source_sha256,
        topic=manifest.topic,
        dataset_role=proposal.dataset_role,
        grain=proposal.grain,
        population_scope=_dataset_population_scope(proposal),
        status=DatasetStatus.PUBLISHED,
        quality_score=manifest.quality.quality_score,
        mapping_version=manifest.mapping_version,
        approved_by=manifest.approved_by,
    )
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    table.put_item(
        Item={
            "dataset_id": metadata.dataset_id,
            "version": metadata.version,
            "metadata_json": metadata.model_dump_json(),
            "quality_score": str(metadata.quality_score),
            "status": metadata.status.value,
        }
    )
    # The pointer the catalog reads to resolve the live version of a dataset.
    table.put_item(
        Item={
            "dataset_id": metadata.dataset_id,
            "version": "__published__",
            "published_version": metadata.version,
        }
    )


def _dataset_population_scope(proposal: "MappingProposal") -> "PopulationScope":
    """The dataset's scope: a metric's scope if declared, else the general default."""
    from youth_compass.domain.contracts import PopulationScope

    for metric in proposal.metrics:
        return metric.population_scope
    return PopulationScope.UNKNOWN


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
