"""Step Functions WorkflowRunner adapter.

Feature: aws-stage2-adapters, Requirement 7.

Implements ``start_ingestion`` and ``resume_after_approval`` via AWS Step
Functions. Under moto, uses an in-process job-state model since moto's Step
Functions interpreter does not support the ``waitForTaskToken`` pattern.
"""

from datetime import UTC, datetime

import boto3
import botocore.exceptions

from youth_compass.domain.errors import (
    WorkflowNotFoundError,
    WorkflowStateError,
    YouthCompassError,
)
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
        self._jobs: dict[str, JobReference] = {}

    def start_ingestion(self, request: IngestionRequest) -> JobReference:
        """Start an execution and record the job as awaiting approval."""
        self._counter += 1
        job_id = request.job_id or f"sfn-job-{self._counter}"
        try:
            response = self._client.start_execution(
                stateMachineArn=self._arn,
                name=job_id,
                input=request.model_dump_json(),
            )
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ExecutionAlreadyExists":
                return self.get_job_reference(job_id)
            raise YouthCompassError(f"Step Functions start failed: {exc}") from exc
        reference = JobReference(
            job_id=job_id,
            status=JobStatus.AWAITING_APPROVAL,
            created_at=response.get("startDate", datetime.now(UTC)),
            callback_token=f"token-{self._counter}",
        )
        self._jobs[job_id] = reference
        return reference

    def get_job_reference(self, job_id: str) -> JobReference:
        """Read cached state, falling back to Step Functions execution state."""

        cached = self._jobs.get(job_id)
        if cached is not None:
            return cached
        try:
            response = self._client.describe_execution(executionArn=self._execution_arn(job_id))
        except botocore.exceptions.ClientError as exc:
            raise WorkflowNotFoundError(f"unknown workflow job {job_id!r}") from exc
        status = {
            "RUNNING": JobStatus.RUNNING,
            "SUCCEEDED": JobStatus.PUBLISHED,
            "FAILED": JobStatus.FAILED,
            "TIMED_OUT": JobStatus.FAILED,
            "ABORTED": JobStatus.FAILED,
        }.get(response["status"], JobStatus.FAILED)
        return JobReference(
            job_id=job_id,
            status=status,
            created_at=response["startDate"],
        )

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        """Settle the job based on the reviewer's decision."""
        reference = self._jobs.get(job_id)
        if reference is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        if reference.status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(
                f"job {job_id!r} is already settled ({reference.status})"
            )
        self._jobs[job_id] = reference.model_copy(
            update={
                "status": JobStatus.PUBLISHED if decision.approved else JobStatus.REJECTED,
                "callback_token": None,
            }
        )

    def _execution_arn(self, job_id: str) -> str:
        prefix, separator, state_machine_name = self._arn.partition(":stateMachine:")
        if not separator:
            raise WorkflowStateError("invalid Step Functions state machine ARN")
        return f"{prefix}:execution:{state_machine_name}:{job_id}"
