"""WorkflowRunner contract.

Feature: aws-stage1-foundation. Property 8 (unknown/settled job raises).
"""

from datetime import UTC, datetime

import pytest

from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ports import ApprovalDecision, IngestionRequest, JobStatus, WorkflowRunner


def _decision(approved: bool = True) -> ApprovalDecision:
    return ApprovalDecision(
        approved=approved, decided_by="reviewer", decided_at=datetime(2026, 9, 12, tzinfo=UTC)
    )


class TestWorkflowRunnerContract:
    def test_start_ingestion_returns_job_with_id(self, workflow_runner: WorkflowRunner) -> None:
        job = workflow_runner.start_ingestion(
            IngestionRequest(source_uri="mem://incoming/f.csv", submitted_by="steward")
        )
        assert job.job_id
        assert workflow_runner.get_job_reference(job.job_id).status is job.status

    def test_property_8_resume_unknown_job_raises(self, workflow_runner: WorkflowRunner) -> None:
        with pytest.raises(WorkflowStateError):
            workflow_runner.resume_after_approval("no-such-job", _decision())

    def test_status_reflects_settled_job(self, workflow_runner: WorkflowRunner) -> None:
        job = workflow_runner.start_ingestion(
            IngestionRequest(source_uri="mem://incoming/f.csv", submitted_by="steward")
        )
        workflow_runner.resume_after_approval(job.job_id, _decision())
        assert workflow_runner.get_job_reference(job.job_id).status is JobStatus.PUBLISHED

    def test_property_8_approve_then_approve_is_rejected(
        self, workflow_runner: WorkflowRunner
    ) -> None:
        job = workflow_runner.start_ingestion(
            IngestionRequest(source_uri="mem://incoming/f.csv", submitted_by="steward")
        )
        workflow_runner.resume_after_approval(job.job_id, _decision())
        with pytest.raises(WorkflowStateError):
            workflow_runner.resume_after_approval(job.job_id, _decision())
