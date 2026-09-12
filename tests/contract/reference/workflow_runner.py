"""In-memory WorkflowRunner reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from tests.contract.registry import register_workflow_runner
from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ports import (
    ApprovalDecision,
    IngestionRequest,
    JobReference,
    JobStatus,
    WorkflowRunner,
)


class InMemoryWorkflowRunner:
    """Starts jobs in AWAITING_APPROVAL; resume settles them exactly once."""

    def __init__(self) -> None:
        self._counter = 0
        self._status: dict[str, JobStatus] = {}

    def start_ingestion(self, request: IngestionRequest) -> JobReference:
        self._counter += 1
        job_id = f"job-{self._counter}"
        self._status[job_id] = JobStatus.AWAITING_APPROVAL
        return JobReference(
            job_id=job_id,
            status=JobStatus.AWAITING_APPROVAL,
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
            callback_token=f"token-{self._counter}",
        )

    def get_job_reference(self, job_id: str) -> JobReference:
        status = self._status.get(job_id)
        if status is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        return JobReference(
            job_id=job_id,
            status=status,
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
            callback_token=(
                f"token-{job_id.removeprefix('job-')}"
                if status is JobStatus.AWAITING_APPROVAL
                else None
            ),
        )

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        status = self._status.get(job_id)
        if status is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        if status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(f"job {job_id!r} is already settled ({status})")
        self._status[job_id] = JobStatus.PUBLISHED if decision.approved else JobStatus.REJECTED


@register_workflow_runner("reference")
@contextmanager
def _reference_workflow_runner() -> Iterator[WorkflowRunner]:
    yield InMemoryWorkflowRunner()
