"""DynamoDB-backed durable workflow checkpoints.

Feature: aws-stage2-adapters (PR2 — Production Ingestion Workflow).

Replaces in-memory workflow state so a job survives API and Lambda restarts.
Implements the CheckpointStore port: the latest checkpoint per workflow lives
under sort key ``CHECKPOINT``, and each transition is also appended under a
timestamped sort key for an audit history.

The table is the same on-demand metadata table the DataStack provisions; this
adapter uses a distinct ``dataset_id`` namespace (``wf#<workflow_id>``) so it
does not collide with catalog records.
"""

import boto3
import botocore.exceptions

from youth_compass.domain.errors import WorkflowPersistenceError
from youth_compass.ports import WorkflowCheckpoint

_LATEST_SORT_KEY = "CHECKPOINT"
_HISTORY_PREFIX = "HISTORY#"


def _pk(workflow_id: str) -> str:
    return f"wf#{workflow_id}"


class DynamoDBCheckpointStore:
    """Persist workflow checkpoints in DynamoDB (durable across restarts)."""

    def __init__(self, table_name: str, region: str = "us-east-1") -> None:
        self._table_name = table_name
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def save(self, workflow_id: str, checkpoint: WorkflowCheckpoint) -> None:
        if checkpoint.workflow_id != workflow_id:
            raise WorkflowPersistenceError("checkpoint workflow_id does not match storage key")
        payload = checkpoint.model_dump_json()
        saved_at = checkpoint.saved_at.isoformat()
        try:
            # Latest pointer (overwritten each transition).
            self._table.put_item(
                Item={
                    "dataset_id": _pk(workflow_id),
                    "version": _LATEST_SORT_KEY,
                    "checkpoint_json": payload,
                    "saved_at": saved_at,
                }
            )
            # Append-only history entry.
            self._table.put_item(
                Item={
                    "dataset_id": _pk(workflow_id),
                    "version": f"{_HISTORY_PREFIX}{saved_at}#{checkpoint.node}",
                    "checkpoint_json": payload,
                    "saved_at": saved_at,
                }
            )
        except botocore.exceptions.ClientError as exc:
            raise WorkflowPersistenceError(f"cannot save workflow {workflow_id!r}") from exc

    def load(self, workflow_id: str) -> WorkflowCheckpoint | None:
        try:
            response = self._table.get_item(
                Key={"dataset_id": _pk(workflow_id), "version": _LATEST_SORT_KEY}
            )
        except botocore.exceptions.ClientError as exc:
            raise WorkflowPersistenceError(f"cannot load workflow {workflow_id!r}") from exc
        item = response.get("Item")
        if item is None:
            return None
        return WorkflowCheckpoint.model_validate_json(item["checkpoint_json"])

    def list_history(self, workflow_id: str) -> list[WorkflowCheckpoint]:
        """Return append-only state transitions for audit and debugging."""
        from boto3.dynamodb.conditions import Key

        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("dataset_id").eq(_pk(workflow_id))
                    & Key("version").begins_with(_HISTORY_PREFIX)
                )
            )
        except botocore.exceptions.ClientError as exc:
            raise WorkflowPersistenceError(f"cannot load workflow history {workflow_id!r}") from exc
        return [
            WorkflowCheckpoint.model_validate_json(item["checkpoint_json"])
            for item in response.get("Items", [])
        ]
