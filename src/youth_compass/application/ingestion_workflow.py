"""Portable ingestion orchestration with a durable human-approval checkpoint."""

import hashlib
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from pydantic import BaseModel, Field

from youth_compass.domain.contracts import (
    DatasetMetadata,
    DatasetStatus,
    MappingAnalysis,
    PopulationScope,
    PublicationManifest,
    PublicationStatus,
)
from youth_compass.domain.errors import WorkflowNotFoundError, WorkflowStateError
from youth_compass.domain.types import FileFormat
from youth_compass.ingestion import profile_csv
from youth_compass.mapping import MappingOptions, MappingProposalError, analyze_mapping
from youth_compass.ports import (
    ApprovalDecision,
    CheckpointStore,
    Clock,
    DataCatalog,
    IngestionRequest,
    JobReference,
    JobStatus,
    ObjectStore,
    SourceAdapter,
    WorkflowCheckpoint,
)
from youth_compass.transformation import TransformOptions, run_csv_transformation


class IngestionJob(BaseModel):
    """Serializable state returned to review and status endpoints."""

    job_id: str = Field(min_length=1)
    status: JobStatus
    source_uri: str
    source_name: str
    source_format: FileFormat = FileFormat.CSV
    source_warnings: list[str] = Field(default_factory=list)
    normalized_uri: str | None = None
    normalized_name: str | None = None
    submitted_by: str
    dataset_id: str
    metadata: DatasetMetadata
    mapping_analysis: MappingAnalysis
    callback_token: str | None = None
    decision: ApprovalDecision | None = None
    manifest: PublicationManifest | None = None


@dataclass(frozen=True, slots=True)
class LocalWorkflowOptions:
    """Local publication paths and deterministic transform policy."""

    curated_root: Path
    quarantine_root: Path
    batch_size: int = 10_000
    max_rejection_rate: float = 0.01
    transformation_version: str = "canonical-v1"


class LocalIngestionWorkflow:
    """Coordinate onboarding without depending on local or AWS implementations."""

    def __init__(
        self,
        *,
        object_store: ObjectStore,
        catalog: DataCatalog,
        checkpoints: CheckpointStore,
        clock: Clock,
        source_adapter: SourceAdapter,
        options: LocalWorkflowOptions,
    ) -> None:
        self._objects = object_store
        self._catalog = catalog
        self._checkpoints = checkpoints
        self._clock = clock
        self._source_adapter = source_adapter
        self._options = options

    def submit_file(
        self,
        source: Path,
        *,
        submitted_by: str,
        topic_hint: str | None = None,
    ) -> JobReference:
        """Persist original bytes, then start a durable ingestion workflow."""

        if not submitted_by.strip():
            raise WorkflowStateError("submitted_by must not be empty")
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise WorkflowStateError(f"cannot read source file {source}") from exc
        return self.submit_bytes(
            file_name=source.name,
            content=content,
            submitted_by=submitted_by,
            topic_hint=topic_hint,
        )

    def submit_bytes(
        self,
        *,
        file_name: str,
        content: bytes,
        submitted_by: str,
        topic_hint: str | None = None,
    ) -> JobReference:
        """Store uploaded bytes and start the same durable workflow."""

        safe_name = Path(file_name).name
        if not safe_name:
            raise WorkflowStateError("source file name must not be empty")
        if not content:
            raise WorkflowStateError("source file must not be empty")
        if not submitted_by.strip():
            raise WorkflowStateError("submitted_by must not be empty")
        checksum = hashlib.sha256(content).hexdigest()
        source_uri = self._objects.put(
            f"incoming/{checksum}/{safe_name}",
            content,
            {"file_name": safe_name, "submitted_by": submitted_by.strip(), "sha256": checksum},
        )
        return self.start_ingestion(
            IngestionRequest(
                source_uri=source_uri,
                submitted_by=submitted_by.strip(),
                topic_hint=topic_hint,
            )
        )

    def start_ingestion(self, request: IngestionRequest) -> JobReference:
        """Normalize, profile, and map a stored source, then pause for approval."""

        content = self._objects.get(request.source_uri)
        source_name = _source_name(request.source_uri)
        normalized = self._source_adapter.normalize(source_name, content)
        original_checksum = hashlib.sha256(content).hexdigest()
        normalized_uri = self._objects.put(
            f"standardized/{original_checksum}/{normalized.file_name}",
            normalized.content,
            {
                "source_uri": request.source_uri,
                "source_format": normalized.source_format.value,
                "sha256": hashlib.sha256(normalized.content).hexdigest(),
            },
        )
        analysis = self._analyze(
            normalized.content,
            normalized.file_name,
            source_name,
            normalized.source_format,
            len(content),
            original_checksum,
            request.topic_hint,
        )
        dataset_id = _dataset_id(analysis.proposal.topic)
        now = self._clock.now()
        status = JobStatus.AWAITING_APPROVAL if analysis.validation.valid else JobStatus.QUARANTINED
        callback_token = uuid.uuid4().hex if status is JobStatus.AWAITING_APPROVAL else None
        metadata = DatasetMetadata(
            dataset_id=dataset_id,
            version=f"received-{original_checksum[:16]}",
            source_uri=request.source_uri,
            source_sha256=original_checksum,
            topic=analysis.proposal.topic,
            dataset_role=analysis.proposal.dataset_role,
            grain=analysis.proposal.grain,
            population_scope=_population_scope(analysis),
            status=(
                DatasetStatus.AWAITING_APPROVAL
                if status is JobStatus.AWAITING_APPROVAL
                else DatasetStatus.QUARANTINED
            ),
            quality_score=analysis.validation.overall_confidence,
            created_at=now,
        )
        job = IngestionJob(
            job_id=f"job-{uuid.uuid4().hex}",
            status=status,
            source_uri=request.source_uri,
            source_name=source_name,
            source_format=normalized.source_format,
            source_warnings=list(normalized.warnings),
            normalized_uri=normalized_uri,
            normalized_name=normalized.file_name,
            submitted_by=request.submitted_by,
            dataset_id=dataset_id,
            metadata=metadata,
            mapping_analysis=analysis,
            callback_token=callback_token,
        )
        self._catalog.register(metadata)
        self._save(job, node=status.value)
        return JobReference(
            job_id=job.job_id,
            status=job.status,
            created_at=now,
            callback_token=callback_token,
        )

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        """Settle a paused job once, publishing only after explicit approval."""

        job = self.get_job(job_id)
        if job.status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(f"job {job_id!r} is already settled ({job.status})")
        if decision.mapping_overrides:
            raise WorkflowStateError("mapping overrides are not supported by the deterministic MVP")
        if not decision.approved:
            metadata = job.metadata.model_copy(
                update={"status": DatasetStatus.REJECTED, "approved_by": decision.decided_by}
            )
            rejected = job.model_copy(
                update={
                    "status": JobStatus.REJECTED,
                    "metadata": metadata,
                    "decision": decision,
                    "callback_token": None,
                }
            )
            self._catalog.register(metadata)
            self._save(rejected, node=JobStatus.REJECTED.value)
            return

        try:
            manifest = self._transform(job, decision)
        except Exception:
            failed = job.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "decision": decision,
                    "callback_token": None,
                }
            )
            self._save(failed, node=JobStatus.FAILED.value)
            raise

        published = manifest.status is PublicationStatus.PUBLISHED
        status = JobStatus.PUBLISHED if published else JobStatus.QUARANTINED
        metadata = DatasetMetadata(
            dataset_id=job.dataset_id,
            version=manifest.dataset_version,
            source_uri=job.source_uri,
            source_sha256=manifest.source_sha256,
            topic=manifest.topic,
            dataset_role=job.mapping_analysis.proposal.dataset_role,
            grain=job.mapping_analysis.proposal.grain,
            population_scope=_population_scope(job.mapping_analysis),
            status=DatasetStatus.PUBLISHED if published else DatasetStatus.QUARANTINED,
            quality_score=manifest.quality.quality_score,
            mapping_version=manifest.mapping_version,
            approved_by=decision.decided_by,
            created_at=job.metadata.created_at,
            published_at=decision.decided_at if published else None,
        )
        settled = job.model_copy(
            update={
                "status": status,
                "metadata": metadata,
                "decision": decision,
                "manifest": manifest,
                "callback_token": None,
            }
        )
        self._catalog.register(metadata)
        self._save(settled, node=status.value)

    def get_job(self, job_id: str) -> IngestionJob:
        """Load the latest durable job state for status and review views."""

        checkpoint = self._checkpoints.load(job_id)
        if checkpoint is None:
            raise WorkflowNotFoundError(f"unknown workflow job {job_id!r}")
        payload = checkpoint.state.get("job")
        if not isinstance(payload, dict):
            raise WorkflowStateError(f"workflow job {job_id!r} has an invalid checkpoint")
        return IngestionJob.model_validate(payload)

    def get_job_reference(self, job_id: str) -> JobReference:
        """Return the portable status projection required by WorkflowRunner."""

        job = self.get_job(job_id)
        return JobReference(
            job_id=job.job_id,
            status=job.status,
            created_at=job.metadata.created_at,
            callback_token=job.callback_token,
        )

    def _analyze(
        self,
        content: bytes,
        normalized_name: str,
        source_name: str,
        source_format: FileFormat,
        source_size: int,
        source_checksum: str,
        topic_hint: str | None,
    ) -> MappingAnalysis:
        try:
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / normalized_name
                source.write_bytes(content)
                profile = profile_csv(source).model_copy(
                    update={
                        "source_path": Path(source_name),
                        "file_name": source_name,
                        "file_format": source_format,
                        "file_size_bytes": source_size,
                        "content_sha256": source_checksum,
                    }
                )
                return analyze_mapping(profile, MappingOptions(topic_hint=topic_hint))
        except (OSError, MappingProposalError, ValueError) as exc:
            raise WorkflowStateError(f"cannot analyze source {source_name!r}: {exc}") from exc

    def _transform(self, job: IngestionJob, decision: ApprovalDecision) -> PublicationManifest:
        normalized_uri = job.normalized_uri or job.source_uri
        normalized_name = job.normalized_name or job.source_name
        content = self._objects.get(normalized_uri)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / normalized_name
            source.write_bytes(content)
            return run_csv_transformation(
                source,
                TransformOptions(
                    approved_by=decision.decided_by,
                    curated_root=self._options.curated_root,
                    quarantine_root=self._options.quarantine_root,
                    dataset_id=job.dataset_id,
                    topic_hint=job.mapping_analysis.proposal.topic,
                    batch_size=self._options.batch_size,
                    max_rejection_rate=self._options.max_rejection_rate,
                    transformation_version=self._options.transformation_version,
                    source_uri=job.source_uri,
                    source_sha256=job.metadata.source_sha256,
                ),
            )

    def _save(self, job: IngestionJob, *, node: str) -> None:
        self._checkpoints.save(
            job.job_id,
            WorkflowCheckpoint(
                workflow_id=job.job_id,
                node=node,
                state={"job": job.model_dump(mode="json")},
                saved_at=self._clock.now(),
            ),
        )


def _source_name(source_uri: str) -> str:
    name = unquote(source_uri.rsplit("/", 1)[-1])
    return name


def _dataset_id(topic: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", topic.casefold()).strip("_")
    if not normalized or not normalized[0].isalpha():
        raise WorkflowStateError(
            "topic cannot form a dataset_id; provide a deterministic ASCII topic hint"
        )
    return normalized


def _population_scope(analysis: MappingAnalysis) -> PopulationScope:
    scopes = {metric.population_scope for metric in analysis.proposal.metrics}
    return next(iter(scopes)) if len(scopes) == 1 else PopulationScope.UNKNOWN
