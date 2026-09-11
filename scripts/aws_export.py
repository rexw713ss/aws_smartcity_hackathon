"""Local data exporter for account suspension.

Feature: aws-stage1-foundation, design 3.5.5.

Pulls every project S3 object and Glue catalog record onto local disk before the
hackathon organizer suspends the account. Idempotent (skips unchanged files),
resumable, and honest about checksums:

    uv run python scripts/aws_export.py --dest ./exports/aws \
        --bucket my-curated-bucket --database youth_compass
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import boto3
import botocore.exceptions
from pydantic import BaseModel, Field

from scripts.aws_common import RegionError, boto_config, validate_region

_MAX_ATTEMPTS = 3
_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 10.0


class ExportOutcome(StrEnum):
    EXPORTED = "exported"
    SKIPPED = "skipped"
    FAILED = "failed"


class ChecksumAlgorithm(StrEnum):
    SHA256 = "sha256"
    ETAG_MD5 = "etag-md5"
    ETAG_MULTIPART = "etag-multipart"


class ExportEntry(BaseModel):
    source_uri: str
    destination_path: str
    size_bytes: int = Field(ge=0)
    remote_checksum: str | None = None
    local_checksum: str | None = None
    checksum_algorithm: ChecksumAlgorithm
    checksum_comparable: bool
    outcome: ExportOutcome
    reason: str | None = None


class CatalogExportEntry(BaseModel):
    database: str
    table: str | None = None
    destination_path: str
    outcome: ExportOutcome
    reason: str | None = None


class ExportManifest(BaseModel):
    tool: str = "aws-export"
    region: str
    started_at: datetime
    destination: str
    objects: list[ExportEntry] = Field(default_factory=list)
    catalog: list[CatalogExportEntry] = Field(default_factory=list)
    exported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_bytes: int = 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_destination(dest_root: Path, bucket: str, key: str) -> Path | None:
    if key.startswith("/") or ".." in Path(key).parts or key.endswith("/"):
        return None
    target = (dest_root / bucket / key).resolve()
    root = (dest_root / bucket).resolve()
    if root not in target.parents and target != root:
        return None
    return target


def _resolve_checksum(head: dict[str, Any]) -> tuple[str | None, ChecksumAlgorithm, bool]:
    if head.get("ChecksumSHA256"):
        return head["ChecksumSHA256"], ChecksumAlgorithm.SHA256, True
    etag = head.get("ETag", "").strip('"')
    if etag and "-" not in etag:
        return etag, ChecksumAlgorithm.ETAG_MD5, False  # md5, not comparable to sha256
    return etag or None, ChecksumAlgorithm.ETAG_MULTIPART, False


class DataExporter:
    def __init__(self, session: boto3.session.Session, region: str, dest: Path) -> None:
        self._s3 = session.client("s3", region_name=region, config=boto_config())
        self._glue = session.client("glue", region_name=region, config=boto_config())
        self._dest = dest

    def _list_objects(self, bucket: str) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            objects.extend(page.get("Contents", []))
        return objects

    def export_object(self, bucket: str, obj: dict[str, Any], *, dry_run: bool) -> ExportEntry:
        key = obj["Key"]
        source_uri = f"s3://{bucket}/{key}"
        size = int(obj.get("Size", 0))
        target = _safe_destination(self._dest, bucket, key)
        if target is None:
            return ExportEntry(
                source_uri=source_uri,
                destination_path="",
                size_bytes=size,
                checksum_algorithm=ChecksumAlgorithm.ETAG_MULTIPART,
                checksum_comparable=False,
                outcome=ExportOutcome.FAILED,
                reason="unsafe object key cannot be written beneath the destination",
            )
        rel = str(target.relative_to(self._dest))
        head = self._retry(
            lambda: self._s3.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        )
        remote, algo, comparable = _resolve_checksum(head)

        if dry_run:
            return ExportEntry(
                source_uri=source_uri,
                destination_path=rel,
                size_bytes=size,
                remote_checksum=remote,
                checksum_algorithm=algo,
                checksum_comparable=comparable,
                outcome=ExportOutcome.SKIPPED,
                reason="dry-run",
            )

        if target.exists() and comparable and remote:
            local = _sha256_file(target)
            if local == remote:
                return ExportEntry(
                    source_uri=source_uri,
                    destination_path=rel,
                    size_bytes=size,
                    remote_checksum=remote,
                    local_checksum=local,
                    checksum_algorithm=algo,
                    checksum_comparable=comparable,
                    outcome=ExportOutcome.SKIPPED,
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        self._retry(lambda: self._s3.download_file(bucket, key, str(target)))
        local = _sha256_file(target)
        reason = None
        outcome = ExportOutcome.EXPORTED
        if comparable and remote and local != remote:
            outcome = ExportOutcome.FAILED
            reason = f"checksum mismatch expected={remote} observed={local}"
        return ExportEntry(
            source_uri=source_uri,
            destination_path=rel,
            size_bytes=size,
            remote_checksum=remote,
            local_checksum=local,
            checksum_algorithm=algo,
            checksum_comparable=comparable,
            outcome=outcome,
            reason=reason,
        )

    def export_database(self, database: str, *, dry_run: bool) -> list[CatalogExportEntry]:
        entries: list[CatalogExportEntry] = []
        db_dir = self._dest / "_catalog" / database
        try:
            db = self._retry(lambda: self._glue.get_database(Name=database))["Database"]
            tables = self._retry(lambda: self._glue.get_tables(DatabaseName=database)).get(
                "TableList", []
            )
        except botocore.exceptions.ClientError as exc:
            return [
                CatalogExportEntry(
                    database=database,
                    destination_path="",
                    outcome=ExportOutcome.FAILED,
                    reason=f"{type(exc).__name__}",
                )
            ]
        if not dry_run:
            db_dir.mkdir(parents=True, exist_ok=True)
            (db_dir / "database.json").write_text(json.dumps(db, default=str, indent=2))
        entries.append(
            CatalogExportEntry(
                database=database,
                destination_path=str((db_dir / "database.json").relative_to(self._dest)),
                outcome=ExportOutcome.SKIPPED if dry_run else ExportOutcome.EXPORTED,
            )
        )
        for table in tables:
            name = table["Name"]
            path = db_dir / f"table-{name}.json"
            if not dry_run:
                path.write_text(json.dumps(table, default=str, indent=2))
            entries.append(
                CatalogExportEntry(
                    database=database,
                    table=name,
                    destination_path=str(path.relative_to(self._dest)),
                    outcome=ExportOutcome.SKIPPED if dry_run else ExportOutcome.EXPORTED,
                )
            )
        return entries

    @staticmethod
    def _retry[T](call: Callable[[], T]) -> T:
        last: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS + 1):
            try:
                return call()
            except botocore.exceptions.ClientError as exc:
                last = exc
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(min(_MAX_BACKOFF, max(_MIN_BACKOFF, 2.0**attempt)))
        assert last is not None
        raise last


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def run_export(
    region: str,
    dest: Path,
    buckets: list[str],
    databases: list[str],
    *,
    dry_run: bool,
    session: boto3.session.Session | None = None,
) -> ExportManifest:
    session = session or boto3.session.Session()
    dest.mkdir(parents=True, exist_ok=True)
    exporter = DataExporter(session, region, dest)
    manifest = ExportManifest(region=region, started_at=datetime.now(UTC), destination=str(dest))

    planned: list[tuple[str, dict[str, Any]]] = []
    for bucket in buckets:
        for obj in exporter._list_objects(bucket):
            planned.append((bucket, obj))

    total_planned = sum(int(o.get("Size", 0)) for _, o in planned)
    if not dry_run and _free_bytes(dest) < total_planned:
        raise OSError(
            f"insufficient space at {dest}: need {total_planned} bytes, have {_free_bytes(dest)}"
        )

    for bucket, obj in planned:
        entry = exporter.export_object(bucket, obj, dry_run=dry_run)
        manifest.objects.append(entry)
    for database in databases:
        manifest.catalog.extend(exporter.export_database(database, dry_run=dry_run))

    manifest.exported_count = sum(
        1 for e in manifest.objects if e.outcome is ExportOutcome.EXPORTED
    )
    manifest.skipped_count = sum(1 for e in manifest.objects if e.outcome is ExportOutcome.SKIPPED)
    manifest.failed_count = sum(1 for e in manifest.objects if e.outcome is ExportOutcome.FAILED)
    manifest.failed_count += sum(1 for e in manifest.catalog if e.outcome is ExportOutcome.FAILED)
    manifest.total_bytes = sum(
        e.size_bytes for e in manifest.objects if e.outcome is ExportOutcome.EXPORTED
    )

    if not dry_run:
        (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export project S3 and Glue data locally")
    parser.add_argument("--dest", required=True)
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--database", action="append", default=[])
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        region = validate_region(args.region)
    except RegionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    manifest = run_export(
        region,
        Path(args.dest),
        args.bucket,
        args.database,
        dry_run=args.dry_run,
    )
    print(
        f"exported: {manifest.exported_count} objects, {manifest.total_bytes} bytes   "
        f"skipped: {manifest.skipped_count}   failed: {manifest.failed_count}"
    )
    print(f"catalog:  {len({c.database for c in manifest.catalog})} databases")
    print(f"manifest: {Path(args.dest) / 'manifest.json'}")
    return 1 if manifest.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
