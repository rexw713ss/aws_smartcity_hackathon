from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters.local import (
    FileSystemObjectStore,
    LocalTabularSourceAdapter,
    SQLiteCatalog,
    SQLiteCheckpointStore,
    SystemClock,
)
from youth_compass.application import LocalIngestionWorkflow, LocalWorkflowOptions
from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ports import ApprovalDecision, JobStatus


def _workflow(tmp_path: Path) -> tuple[LocalIngestionWorkflow, SQLiteCatalog]:
    catalog = SQLiteCatalog(tmp_path / "metadata" / "catalog.sqlite3")
    workflow = LocalIngestionWorkflow(
        object_store=FileSystemObjectStore(tmp_path / "incoming-store"),
        catalog=catalog,
        checkpoints=SQLiteCheckpointStore(tmp_path / "metadata" / "workflow.sqlite3"),
        clock=SystemClock(),
        source_adapter=LocalTabularSourceAdapter(),
        options=LocalWorkflowOptions(
            curated_root=tmp_path / "curated",
            quarantine_root=tmp_path / "quarantined",
            batch_size=100,
        ),
    )
    return workflow, catalog


def _decision(approved: bool) -> ApprovalDecision:
    return ApprovalDecision(
        approved=approved,
        decided_by="reviewer@example.com",
        decided_at=datetime(2026, 9, 12, tzinfo=UTC),
        notes="reviewed in local workflow test",
    )


def _write_population(source: Path, *, district: str = "板橋區") -> None:
    source.write_text(
        f"year,district,age,population\n2025,{district},20-24,100\n",
        encoding="utf-8",
    )


def test_submit_pauses_then_approval_survives_restart_and_publishes(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    workflow, _ = _workflow(tmp_path)

    reference = workflow.submit_file(source, submitted_by="uploader@example.com")

    assert reference.status is JobStatus.AWAITING_APPROVAL
    assert reference.callback_token
    assert not (tmp_path / "curated").exists()
    submitted_job = workflow.get_job(reference.job_id)
    assert submitted_job.mapping_analysis.profile.source_path == Path("population.csv")

    restarted, catalog = _workflow(tmp_path)
    restarted.resume_after_approval(reference.job_id, _decision(approved=True))
    job = restarted.get_job(reference.job_id)

    assert job.status is JobStatus.PUBLISHED
    assert job.callback_token is None
    assert job.manifest is not None
    assert job.manifest.source_uri.startswith("fileobj://")
    assert Path(job.manifest.parquet_uri).is_file()
    assert catalog.published_version("population") == job.manifest.dataset_version
    assert catalog.get("population").version == job.manifest.dataset_version
    history = SQLiteCheckpointStore(tmp_path / "metadata" / "workflow.sqlite3").list_history(
        reference.job_id
    )
    assert [checkpoint.node for checkpoint in history] == ["awaiting_approval", "published"]


def test_rejection_settles_job_without_writing_curated_data(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    workflow, catalog = _workflow(tmp_path)
    reference = workflow.submit_file(source, submitted_by="uploader@example.com")

    workflow.resume_after_approval(reference.job_id, _decision(approved=False))
    job = workflow.get_job(reference.job_id)

    assert job.status is JobStatus.REJECTED
    assert job.metadata.status == "rejected"
    assert catalog.published_version("population") is None
    assert not (tmp_path / "curated").exists()


def test_quality_quarantine_does_not_advance_published_pointer(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n2025,Atlantis,25-29,50\n",
        encoding="utf-8",
    )
    workflow, catalog = _workflow(tmp_path)
    reference = workflow.submit_file(source, submitted_by="uploader@example.com")

    workflow.resume_after_approval(reference.job_id, _decision(approved=True))
    job = workflow.get_job(reference.job_id)

    assert job.status is JobStatus.QUARANTINED
    assert job.manifest is not None
    assert job.manifest.status == "quarantined"
    assert catalog.published_version("population") is None


def test_blocking_mapping_is_quarantined_before_approval(tmp_path: Path) -> None:
    source = tmp_path / "unknown-unit.csv"
    source.write_text(
        "year,district,age,value\n2025,板橋區,20-24,100\n",
        encoding="utf-8",
    )
    workflow, catalog = _workflow(tmp_path)

    reference = workflow.submit_file(source, submitted_by="uploader@example.com")
    job = workflow.get_job(reference.job_id)

    assert reference.status is JobStatus.QUARANTINED
    assert reference.callback_token is None
    assert job.mapping_analysis.validation.valid is False
    assert catalog.published_version(job.dataset_id) is None
    with pytest.raises(WorkflowStateError, match="already settled"):
        workflow.resume_after_approval(reference.job_id, _decision(approved=True))


def test_approval_is_single_use_and_mapping_overrides_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    workflow, _ = _workflow(tmp_path)
    reference = workflow.submit_file(source, submitted_by="uploader@example.com")
    override = _decision(approved=True).model_copy(
        update={"mapping_overrides": {"district": "district_code"}}
    )

    with pytest.raises(WorkflowStateError, match="mapping overrides"):
        workflow.resume_after_approval(reference.job_id, override)

    workflow.resume_after_approval(reference.job_id, _decision(approved=False))
    with pytest.raises(WorkflowStateError, match="already settled"):
        workflow.resume_after_approval(reference.job_id, _decision(approved=True))


def test_unknown_job_raises_domain_error_after_restart(tmp_path: Path) -> None:
    workflow, _ = _workflow(tmp_path)

    with pytest.raises(WorkflowStateError, match="unknown workflow job"):
        workflow.get_job("missing")
