"""Durable DynamoDB store for workflow status and Step Functions task tokens.

Feature: aws-stage2-adapters (PR2 — Production Ingestion Workflow).

Replaces the in-memory approval state in the Step Functions runner. Job status
and the pending human-approval callback token are persisted so a paused workflow
survives an API or Lambda restart. Stored in the shared metadata table under a
``sfn#<job_id>`` namespace, distinct from catalog and checkpoint records.
"""

import boto3
import botocore.exceptions

from youth_compass.domain.errors import WorkflowPersistenceError
from youth_compass.ports.workflow_runner import JobStatus

_ITEM_SORT_KEY = "SFN_STATE"


def _pk(job_id: str) -> str:
    return f"sfn#{job_id}"


class WorkflowTokenStore:
    """Persist job status and the pending approval task token in DynamoDB."""

    def __init__(self, table_name: str, region: str = "us-east-1") -> None:
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put_status(self, job_id: str, status: JobStatus) -> None:
        self._update(job_id, {"status": status.value})

    def get_status(self, job_id: str) -> JobStatus | None:
        item = self._get(job_id)
        if item is None or "status" not in item:
            return None
        return JobStatus(item["status"])

    def put_token(self, job_id: str, task_token: str) -> None:
        self._update(job_id, {"task_token": task_token})

    def get_token(self, job_id: str) -> str | None:
        item = self._get(job_id)
        token = item.get("task_token") if item else None
        return str(token) if token else None

    def clear_token(self, job_id: str) -> None:
        self._update(job_id, {"task_token": None})

    def _update(self, job_id: str, fields: dict[str, str | None]) -> None:
        item = self._get(job_id) or {"dataset_id": _pk(job_id), "version": _ITEM_SORT_KEY}
        for key, value in fields.items():
            if value is None:
                item.pop(key, None)
            else:
                item[key] = value
        try:
            self._table.put_item(Item=item)
        except botocore.exceptions.ClientError as exc:
            raise WorkflowPersistenceError(f"cannot persist workflow state {job_id!r}") from exc

    def _get(self, job_id: str) -> dict[str, str] | None:
        try:
            response = self._table.get_item(
                Key={"dataset_id": _pk(job_id), "version": _ITEM_SORT_KEY}
            )
        except botocore.exceptions.ClientError as exc:
            raise WorkflowPersistenceError(f"cannot read workflow state {job_id!r}") from exc
        return response.get("Item")
