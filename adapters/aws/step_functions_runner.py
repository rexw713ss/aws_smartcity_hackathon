"""Step Functions WorkflowRunner adapter.

Feature: aws-stage2-adapters, Requirement 7.

Implements ``start_ingestion`` and ``resume_after_approval`` via AWS Step
Functions. Under moto, uses an in-process job-state model since moto's Step
Functions interpreter does not support the ``waitForTaskToken`` pattern.
"""

import json
from datetime import UTC, datetime
from typing import ClassVar

import boto3
import botocore.exceptions

from adapters.aws.workflow_token_store import WorkflowTokenStore
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
    """WorkflowRunner backed by Step Functions with durable, restart-safe state.

    Job state and the human-approval callback token are stored in DynamoDB, so a
    paused workflow survives an API or Lambda restart. ``resume_after_approval``
    returns a real Step Functions task token via SendTaskSuccess/SendTaskFailure.

    When constructed without a token store (for example in the contract suite,
    where moto's Step Functions interpreter does not support waitForTaskToken),
    it falls back to an in-process table so the observable contract still holds.
    """

    _STATUS_MAP: ClassVar[dict[str, JobStatus]] = {
        "RUNNING": JobStatus.RUNNING,
        "SUCCEEDED": JobStatus.PUBLISHED,
        "FAILED": JobStatus.FAILED,
        "TIMED_OUT": JobStatus.FAILED,
        "ABORTED": JobStatus.FAILED,
    }

    def __init__(
        self,
        state_machine_arn: str,
        region: str = "ap-northeast-1",
        *,
        token_store: WorkflowTokenStore | None = None,
    ) -> None:
        self._arn = state_machine_arn
        self._client = boto3.client("stepfunctions", region_name=region)
        self._store = token_store
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
        if self._store is not None:
            self._store.put_status(job_id, reference.status)
        else:
            self._jobs[job_id] = reference
        return reference

    def register_callback_token(self, job_id: str, task_token: str) -> None:
        """Persist the real Step Functions task token for a paused job.

        Called by the workflow's approval task (the waitForTaskToken step) so a
        later approval can resume the exact suspended execution.
        """
        if self._store is None:
            raise WorkflowStateError("a durable token store is required to persist task tokens")
        self._store.put_token(job_id, task_token)

    def get_job_reference(self, job_id: str) -> JobReference:
        """Read durable state, falling back to Step Functions execution state."""
        if self._store is not None:
            status = self._store.get_status(job_id)
            if status is not None:
                return JobReference(job_id=job_id, status=status, created_at=datetime.now(UTC))
        else:
            cached = self._jobs.get(job_id)
            if cached is not None:
                return cached
        try:
            response = self._client.describe_execution(executionArn=self._execution_arn(job_id))
        except botocore.exceptions.ClientError as exc:
            raise WorkflowNotFoundError(f"unknown workflow job {job_id!r}") from exc
        status = self._STATUS_MAP.get(response["status"], JobStatus.FAILED)
        return JobReference(job_id=job_id, status=status, created_at=response["startDate"])

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        """Settle the job by returning the real task token to Step Functions."""
        if self._store is None:
            return self._resume_in_memory(job_id, decision)

        status = self._store.get_status(job_id)
        if status is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        if status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(f"job {job_id!r} is already settled ({status})")
        token = self._store.get_token(job_id)
        if token is None:
            raise WorkflowStateError(f"job {job_id!r} has no pending approval token")

        try:
            if decision.approved:
                self._client.send_task_success(
                    taskToken=token,
                    output=json.dumps({"approved": True, "decided_by": decision.decided_by}),
                )
            else:
                self._client.send_task_failure(
                    taskToken=token,
                    error="Rejected",
                    cause=decision.notes or "rejected by reviewer",
                )
        except botocore.exceptions.ClientError as exc:
            raise YouthCompassError(f"failed to resume workflow {job_id!r}: {exc}") from exc

        self._store.put_status(
            job_id, JobStatus.PUBLISHED if decision.approved else JobStatus.REJECTED
        )
        self._store.clear_token(job_id)

    def _resume_in_memory(self, job_id: str, decision: ApprovalDecision) -> None:
        reference = self._jobs.get(job_id)
        if reference is None:
            raise WorkflowStateError(f"unknown workflow job {job_id!r}")
        if reference.status is not JobStatus.AWAITING_APPROVAL:
            raise WorkflowStateError(f"job {job_id!r} is already settled ({reference.status})")
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
