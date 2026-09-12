"""Durable DynamoDB store for structured conversation context.

Replaces the process-local follow-up memory. The default in-memory store lives
inside one API process, so on a multi-instance deployment a follow-up routed to
another instance silently loses its scope. Records are held in the shared
metadata table under a ``ses#<session_id>`` namespace, distinct from catalog,
checkpoint, and workflow records, and expire through the table's native TTL.

Only the structured fields of ``ConversationContext`` are written. No question
text, answer text, or model reasoning reaches this table.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import boto3
import botocore.exceptions

from youth_compass.agent.contracts import ConversationContext
from youth_compass.domain.errors import ConversationPersistenceError

_ITEM_SORT_KEY = "CONVERSATION_CONTEXT"
# Must match the table's configured TTL attribute. DynamoDB reads it as epoch
# seconds and deletes the item some time after it passes.
_TTL_ATTRIBUTE = "expires_at"


def _pk(session_id: str) -> str:
    return f"ses#{session_id}"


class DynamoDbConversationContextStore:
    """Persist one structured context per session, expiring it by table TTL."""

    def __init__(
        self,
        table_name: str,
        region: str = "us-east-1",
        ttl_seconds: int = 1_800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def get(self, session_id: str) -> ConversationContext | None:
        try:
            response = self._table.get_item(
                Key={"dataset_id": _pk(session_id), "version": _ITEM_SORT_KEY}
            )
        except botocore.exceptions.ClientError as exc:
            raise ConversationPersistenceError(
                f"cannot read conversation context {session_id!r}"
            ) from exc
        item = response.get("Item")
        if item is None or "context" not in item:
            return None
        # DynamoDB deletes expired items lazily, so the deadline is enforced on
        # read as well. Without this a long-idle session could still inherit.
        expires_at = _expiry(item)
        if expires_at is not None and expires_at <= int(self._clock().timestamp()):
            return None
        try:
            context = ConversationContext.model_validate_json(str(item["context"]))
        except ValueError as exc:
            # A record written by an older contract is discarded, not repaired.
            raise ConversationPersistenceError(
                f"stored conversation context {session_id!r} does not match the contract"
            ) from exc
        if context.session_id != session_id:
            raise ConversationPersistenceError("stored conversation context has a foreign key")
        return context

    def put(self, context: ConversationContext) -> None:
        try:
            self._table.put_item(
                Item={
                    "dataset_id": _pk(context.session_id),
                    "version": _ITEM_SORT_KEY,
                    "revision": context.revision,
                    _TTL_ATTRIBUTE: int(context.updated_at.timestamp()) + self._ttl_seconds,
                    "context": context.model_dump_json(),
                },
                # An out-of-order write from a concurrent turn must not replace a
                # newer revision, matching the in-memory store's guard.
                ConditionExpression="attribute_not_exists(revision) OR revision < :revision",
                ExpressionAttributeValues={":revision": context.revision},
            )
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return
            raise ConversationPersistenceError(
                f"cannot persist conversation context {context.session_id!r}"
            ) from exc


def _expiry(item: dict[str, object]) -> int | None:
    raw = item.get(_TTL_ATTRIBUTE)
    if raw is None:
        return None
    try:
        return int(str(raw))
    except ValueError:
        return None
