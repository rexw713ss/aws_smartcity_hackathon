"""Offline CSV-to-Parquet vertical slice with quality and publication gates."""

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from youth_compass.domain.contracts import (
    MappingAnalysis,
    MappingProposal,
    PublicationManifest,
    PublicationStatus,
    QualityIssue,
    QualityReport,
    QualityStatus,
)
from youth_compass.domain.types import WarningSeverity
from youth_compass.ingestion import CsvProfileOptions, profile_csv
from youth_compass.mapping import MappingOptions, analyze_mapping
from youth_compass.transformation.schema import (
    CANONICAL_OBSERVATION_SCHEMA,
    REJECTED_ROW_SCHEMA,
)
from youth_compass.transformation.values import (
    LineageContext,
    RowTransformationError,
    transform_row,
)

_DATASET_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class TransformationError(ValueError):
    """The approved mapping cannot be transformed or pass publication gates."""


class PublicationConflictError(TransformationError):
    """An immutable version path exists but does not match this transformation."""


@dataclass(frozen=True, slots=True)
class TransformOptions:
    approved_by: str
    curated_root: Path = Path("data/curated")
    quarantine_root: Path = Path("data/quarantined")
    dataset_id: str | None = None
    topic_hint: str | None = None
    max_rows: int | None = None
    batch_size: int = 10_000
    max_rejection_rate: float = 0.01
    transformation_version: str = "canonical-v1"
    source_uri: str | None = None
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise ValueError("approved_by must not be empty")
        if self.dataset_id is not None and not _DATASET_ID_PATTERN.fullmatch(self.dataset_id):
            raise ValueError("dataset_id must match ^[a-z][a-z0-9_]*$")
        if self.max_rows is not None and self.max_rows < 1:
            raise ValueError("max_rows must be positive when provided")
        if self.batch_size < 100:
            raise ValueError("batch_size must be at least 100")
        if not 0.0 <= self.max_rejection_rate <= 1.0:
            raise ValueError("max_rejection_rate must be between 0 and 1")
        if not self.transformation_version.strip():
            raise ValueError("transformation_version must not be empty")
        if self.source_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("source_sha256 must contain 64 lowercase hexadecimal characters")


def run_csv_transformation(source: Path, options: TransformOptions) -> PublicationManifest:
    """Profile, map, transform, quality-check, and atomically publish one CSV."""

    profile = profile_csv(source, CsvProfileOptions(max_rows=options.max_rows))
    analysis = analyze_mapping(profile, MappingOptions(topic_hint=options.topic_hint))
    if not analysis.validation.valid:
        blocking_codes = sorted(
            issue.code for issue in analysis.validation.issues if issue.blocking
        )
        raise TransformationError("Mapping validation failed: " + ", ".join(blocking_codes))

    dataset_id = options.dataset_id or _default_dataset_id(analysis.proposal.topic)
    mapping_version = _mapping_version(analysis.proposal)
    source_sha256 = options.source_sha256 or profile.content_sha256
    dataset_version = _dataset_version(
        source_sha256,
        mapping_version,
        options.transformation_version,
        options.max_rows,
    )
    curated_final = options.curated_root.resolve() / dataset_id / f"version={dataset_version}"
    quarantine_final = options.quarantine_root.resolve() / dataset_id / f"version={dataset_version}"
    existing = _find_existing_manifest(
        (curated_final, quarantine_final),
        source_sha256=source_sha256,
        mapping_version=mapping_version,
        transformation_version=options.transformation_version,
        is_sample=options.max_rows is not None,
    )
    if existing is not None:
        return existing.model_copy(update={"reused": True})

    staging_parent = options.curated_root.resolve().parent / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{dataset_id}-{dataset_version}-", dir=staging_parent))
    try:
        counts = _write_transformed_parquet(
            source=source.resolve(),
            analysis=analysis,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            mapping_version=mapping_version,
            options=options,
            staging=staging,
        )
        quality = _evaluate_quality(
            parquet_path=staging / "part-000.parquet",
            proposal=analysis.proposal,
            rows_received=counts.rows_received,
            rows_rejected=counts.rows_rejected,
            observation_count=counts.observation_count,
            estimated_observation_count=counts.estimated_observation_count,
            max_rejection_rate=options.max_rejection_rate,
        )
        status = (
            PublicationStatus.QUARANTINED
            if quality.status == QualityStatus.REJECTED
            else PublicationStatus.PUBLISHED
        )
        final = quarantine_final if status == PublicationStatus.QUARANTINED else curated_final
        if final.exists():
            raise PublicationConflictError(f"Immutable output path already exists: {final}")
        final.parent.mkdir(parents=True, exist_ok=True)

        rejected_path = staging / "rejected-rows.parquet"
        manifest = PublicationManifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            topic=analysis.proposal.topic,
            source_uri=options.source_uri or str(profile.source_path),
            source_sha256=source_sha256,
            mapping_version=mapping_version,
            transformation_version=options.transformation_version,
            approved_by=options.approved_by.strip(),
            status=status,
            output_uri=str(final),
            parquet_uri=str(final / "part-000.parquet"),
            rejected_rows_uri=(
                str(final / "rejected-rows.parquet") if rejected_path.exists() else None
            ),
            is_sample=options.max_rows is not None,
            rows_received=counts.rows_received,
            rows_accepted=counts.rows_received - counts.rows_rejected,
            rows_filtered_out=counts.rows_filtered_out,
            rows_filtered_youth=counts.rows_filtered_youth,
            rows_filtered_totals=counts.rows_filtered_totals,
            rows_rejected=counts.rows_rejected,
            observation_count=counts.observation_count,
            estimated_observation_count=counts.estimated_observation_count,
            quality=quality,
        )
        (staging / "manifest.json").write_text(
            f"{manifest.model_dump_json(indent=2)}\n", encoding="utf-8"
        )
        (staging / "mapping-analysis.json").write_text(
            f"{analysis.model_dump_json(indent=2)}\n", encoding="utf-8"
        )
        os.replace(staging, final)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


@dataclass(frozen=True, slots=True)
class _TransformCounts:
    rows_received: int
    rows_rejected: int
    rows_filtered_out: int
    rows_filtered_youth: int
    rows_filtered_totals: int
    observation_count: int
    estimated_observation_count: int


def _write_transformed_parquet(
    *,
    source: Path,
    analysis: MappingAnalysis,
    dataset_id: str,
    dataset_version: str,
    mapping_version: str,
    options: TransformOptions,
    staging: Path,
) -> _TransformCounts:
    parquet_path = staging / "part-000.parquet"
    rejected_path = staging / "rejected-rows.parquet"
    observations: list[dict[str, object]] = []
    rejected_rows: list[dict[str, object]] = []
    rows_received = 0
    rows_rejected = 0
    rows_filtered_out = 0
    rows_filtered_youth = 0
    rows_filtered_totals = 0
    observation_count = 0
    estimated_observation_count = 0

    observation_writer = pq.ParquetWriter(
        parquet_path,
        CANONICAL_OBSERVATION_SCHEMA,
        compression="zstd",
    )
    rejected_writer: pq.ParquetWriter | None = None
    try:
        with source.open("r", encoding=analysis.profile.encoding, newline="") as source_stream:
            reader = csv.reader(source_stream, delimiter=analysis.profile.delimiter)
            try:
                next(reader)
            except StopIteration as error:
                raise TransformationError("CSV file has no header") from error
            headers = [column.name for column in analysis.profile.columns]
            for source_row_number, raw_row in enumerate(reader, start=2):
                if options.max_rows is not None and rows_received >= options.max_rows:
                    break
                rows_received += 1
                normalized_row = _normalize_row(raw_row, len(headers))
                row = dict(zip(headers, normalized_row, strict=True))
                try:
                    result = transform_row(
                        row,
                        analysis.proposal,
                        LineageContext(
                            source_row_number=source_row_number,
                            source_sha256=analysis.profile.content_sha256,
                            dataset_id=dataset_id,
                            dataset_version=dataset_version,
                            mapping_version=mapping_version,
                            transformation_version=options.transformation_version,
                        ),
                    )
                except RowTransformationError as error:
                    rows_rejected += 1
                    rejected_rows.append(
                        {
                            "source_row_number": source_row_number,
                            "error_code": error.code,
                            "field": error.field,
                            "message": str(error),
                        }
                    )
                else:
                    if result.filter_reason is not None:
                        rows_filtered_out += 1
                        if result.filter_reason == "outside_youth_range":
                            rows_filtered_youth += 1
                        elif result.filter_reason == "verified_total":
                            rows_filtered_totals += 1
                    observations.extend(result.observations)
                    observation_count += len(result.observations)
                    estimated_observation_count += sum(
                        observation["is_estimated"] is True for observation in result.observations
                    )

                if len(observations) >= options.batch_size:
                    _write_batch(observation_writer, observations, CANONICAL_OBSERVATION_SCHEMA)
                    observations.clear()
                if len(rejected_rows) >= options.batch_size:
                    if rejected_writer is None:
                        rejected_writer = pq.ParquetWriter(
                            rejected_path, REJECTED_ROW_SCHEMA, compression="zstd"
                        )
                    _write_batch(rejected_writer, rejected_rows, REJECTED_ROW_SCHEMA)
                    rejected_rows.clear()

        if observations:
            _write_batch(observation_writer, observations, CANONICAL_OBSERVATION_SCHEMA)
        if rejected_rows:
            if rejected_writer is None:
                rejected_writer = pq.ParquetWriter(
                    rejected_path, REJECTED_ROW_SCHEMA, compression="zstd"
                )
            _write_batch(rejected_writer, rejected_rows, REJECTED_ROW_SCHEMA)
    finally:
        observation_writer.close()
        if rejected_writer is not None:
            rejected_writer.close()

    parquet_file = pq.ParquetFile(parquet_path)
    if not parquet_file.schema_arrow.equals(CANONICAL_OBSERVATION_SCHEMA):
        raise TransformationError("Parquet schema verification failed after writing")
    if parquet_file.metadata.num_rows != observation_count:
        raise TransformationError("Parquet row-count verification failed after writing")
    return _TransformCounts(
        rows_received=rows_received,
        rows_rejected=rows_rejected,
        rows_filtered_out=rows_filtered_out,
        rows_filtered_youth=rows_filtered_youth,
        rows_filtered_totals=rows_filtered_totals,
        observation_count=observation_count,
        estimated_observation_count=estimated_observation_count,
    )


def _write_batch(
    writer: pq.ParquetWriter,
    records: list[dict[str, object]],
    schema: pa.Schema,
) -> None:
    writer.write_table(pa.Table.from_pylist(records, schema=schema))


def _evaluate_quality(
    *,
    parquet_path: Path,
    proposal: MappingProposal,
    rows_received: int,
    rows_rejected: int,
    observation_count: int,
    estimated_observation_count: int,
    max_rejection_rate: float,
) -> QualityReport:
    issues: list[QualityIssue] = []
    rejection_rate = rows_rejected / rows_received if rows_received else 0.0
    rejection_blocking = rejection_rate > max_rejection_rate
    if rows_rejected:
        issues.append(
            QualityIssue(
                code="ROW_REJECTIONS",
                message=(
                    f"Rejected {rows_rejected} of {rows_received} source rows "
                    f"({rejection_rate:.2%})"
                ),
                severity=(WarningSeverity.ERROR if rejection_blocking else WarningSeverity.WARNING),
                row_count=rows_rejected,
                blocking=rejection_blocking,
            )
        )
    duplicate_count = _count_duplicate_observations(parquet_path, proposal)
    if duplicate_count:
        issues.append(
            QualityIssue(
                code="DUPLICATE_GRAIN",
                message=(f"Found {duplicate_count} duplicate observations at the declared grain"),
                severity=WarningSeverity.ERROR,
                row_count=duplicate_count,
                blocking=True,
            )
        )
    if estimated_observation_count:
        issues.append(
            QualityIssue(
                code="WEIGHTED_YOUTH_ESTIMATE",
                message=(
                    f"Applied youth overlap weights to {estimated_observation_count} observations"
                ),
                severity=WarningSeverity.WARNING,
                row_count=estimated_observation_count,
            )
        )
    if observation_count == 0:
        issues.append(
            QualityIssue(
                code="NO_PUBLISHABLE_OBSERVATIONS",
                message="Transformation produced no publishable observations",
                severity=WarningSeverity.ERROR,
                blocking=True,
            )
        )

    blocking = any(issue.blocking for issue in issues)
    status = (
        QualityStatus.REJECTED
        if blocking
        else QualityStatus.WARNING
        if issues
        else QualityStatus.VALID
    )
    duplicate_rate = duplicate_count / observation_count if observation_count else 0.0
    quality_score = max(0.0, 1.0 - rejection_rate - min(0.25, duplicate_rate))
    return QualityReport(
        status=status,
        quality_score=round(quality_score, 4),
        rows_received=rows_received,
        rows_accepted=rows_received - rows_rejected,
        rows_rejected=rows_rejected,
        issues=issues,
    )


def _count_duplicate_observations(
    parquet_path: Path,
    proposal: MappingProposal,
) -> int:
    if pq.ParquetFile(parquet_path).metadata.num_rows == 0:
        return 0
    grain = [*proposal.grain.dimensions, "metric_code"]
    quoted_grain = ", ".join(f'"{field}"' for field in grain)
    query = f"""
        SELECT COALESCE(SUM(group_size - 1), 0)
        FROM (
            SELECT COUNT(*) AS group_size
            FROM read_parquet(?)
            GROUP BY {quoted_grain}
            HAVING COUNT(*) > 1
        )
    """
    connection = duckdb.connect(database=":memory:")
    try:
        result = connection.execute(query, [str(parquet_path)]).fetchone()
    finally:
        connection.close()
    return int(result[0]) if result is not None else 0


def _normalize_row(raw_row: list[str], header_count: int) -> list[str]:
    if len(raw_row) < header_count:
        return [*raw_row, *("" for _ in range(header_count - len(raw_row)))]
    return raw_row[:header_count]


def _mapping_version(proposal: MappingProposal) -> str:
    payload = json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"mapping-{hashlib.sha256(payload).hexdigest()[:16]}"


def _dataset_version(
    source_sha256: str,
    mapping_version: str,
    transformation_version: str,
    max_rows: int | None,
) -> str:
    transformation_hash = hashlib.sha256(transformation_version.encode()).hexdigest()[:8]
    base = (
        f"{source_sha256[:12]}-{mapping_version.removeprefix('mapping-')[:12]}-"
        f"t{transformation_hash}"
    )
    return f"{base}-sample{max_rows}" if max_rows is not None else base


def _default_dataset_id(topic: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", topic.casefold()).strip("_")
    if not normalized or not normalized[0].isalpha():
        raise TransformationError(
            "Topic cannot form a dataset_id; provide an explicit ASCII --dataset-id"
        )
    return normalized


def _find_existing_manifest(
    candidates: tuple[Path, Path],
    *,
    source_sha256: str,
    mapping_version: str,
    transformation_version: str,
    is_sample: bool,
) -> PublicationManifest | None:
    for candidate in candidates:
        if not candidate.exists():
            continue
        manifest_path = candidate / "manifest.json"
        if not manifest_path.is_file():
            raise PublicationConflictError(
                f"Immutable output exists without a manifest: {candidate}"
            )
        try:
            manifest = PublicationManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except ValueError as error:
            raise PublicationConflictError(
                f"Existing manifest is invalid: {manifest_path}"
            ) from error
        expected = (
            manifest.source_sha256 == source_sha256
            and manifest.mapping_version == mapping_version
            and manifest.transformation_version == transformation_version
            and manifest.is_sample == is_sample
        )
        if not expected:
            raise PublicationConflictError(
                f"Immutable output manifest does not match this run: {manifest_path}"
            )
        if not Path(manifest.parquet_uri).is_file():
            raise PublicationConflictError(
                f"Existing manifest points to a missing Parquet file: {manifest.parquet_uri}"
            )
        return manifest
    return None
