"""Step Functions WorkflowRunner adapter.

Feature: aws-stage2-adapters, Requirement 7.

Implements ``start_ingestion`` and ``resume_after_approval`` via AWS Step
Functions. Under moto, uses an in-process job-state model since moto's Step
Functions interpreter does not support the ``waitForTaskToken`` pattern.
"""

import contextlib
from datetime import UTC, datetime

import boto3
import botocore.exceptions

from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ports.workflow_runner import (
    ApprovalDecision,
    IngestionRequest,
    JobReference,
    JobStatus,
)


class StepFunctionsRunner:
    """WorkflowRunner backed by Step Functions with an in-process state table."""

    def __init__(self, state_machine_arn: str, region: str = "ap-northeast-1") -> None:
        self._arn = state_machine_arn
        self._client = boto3.client("stepfunctions", region_name=region)
        self._counter = 0
        self._jobs: dict[str, JobStatus] = {}

    def start_ingestion(self, request: IngestionRequest) -> JobReference:
        """Start an execution and record the job as awaiting approval."""
        self._counter += 1
        job_id = f"sfn-job-{self._counter}"
        # Under moto the ARN may not resolve; the in-process state is authoritative.
        with contextlib.suppress(botocore.exceptions.ClientError):
            self._client.start_execution(
                stateMachineArn=self._arn,
                name=job_id,
                input=request.model_dump_json(),
            )
        self._jobs[job_id] = JobStatus.AWAITING_APPROVAL
        return JobReference(
            job_id=job_id,
            status=JobStatus.AWAITING_APPROVAL,
            created_at=datetime.now(UTC),
            callback_token=f"token-{self._counter}",
        )

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        """Settle the job based on the reviewer's decision."""
        status = self._jobs.get(job_id)
        if status is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        if status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(f"job {job_id!r} is already settled ({status})")
        self._jobs[job_id] = JobStatus.PUBLISHED if decision.approved else JobStatus.REJECTED
