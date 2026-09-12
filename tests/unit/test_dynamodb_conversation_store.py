"""Behaviour specific to the durable conversation store, beyond the shared contract."""

from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from adapters.aws.conversation_context_store import DynamoDbConversationContextStore
from youth_compass.agent import AnalysisOperation, ConversationContext
from youth_compass.domain.errors import ConversationPersistenceError

_TABLE = "unit-conversation-context"
_REGION = "us-east-1"
_SESSION_ID = "ses_0123456789abcdef0123456789abcdef"
_NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def _create_table() -> None:
    boto3.resource("dynamodb", region_name=_REGION).create_table(
        TableName=_TABLE,
        KeySchema=[
            {"AttributeName": "dataset_id", "KeyType": "HASH"},
            {"AttributeName": "version", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "dataset_id", "AttributeType": "S"},
            {"AttributeName": "version", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _context() -> ConversationContext:
    return ConversationContext(
        session_id=_SESSION_ID,
        objective="compare observations",
        metric_terms=("population_count",),
        entity_ids=("banqiao",),
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
        updated_at=_NOW,
    )


def test_an_idle_session_expires_even_before_dynamodb_deletes_it() -> None:
    # DynamoDB removes expired items lazily, so the deadline is also enforced
    # on read. Otherwise a long-idle scope could still narrow a later answer.
    current = _NOW
    with mock_aws():
        _create_table()
        store = DynamoDbConversationContextStore(
            table_name=_TABLE, region=_REGION, ttl_seconds=300, clock=lambda: current
        )
        store.put(_context())

        assert store.get(_SESSION_ID) is not None
        current = _NOW + timedelta(seconds=301)
        assert store.get(_SESSION_ID) is None


def test_a_record_written_by_an_older_contract_is_rejected_not_repaired() -> None:
    with mock_aws():
        _create_table()
        boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE).put_item(
            Item={
                "dataset_id": f"ses#{_SESSION_ID}",
                "version": "CONVERSATION_CONTEXT",
                "revision": 1,
                "context": '{"session_id": "ses_0123456789abcdef0123456789abcdef"}',
            }
        )
        store = DynamoDbConversationContextStore(table_name=_TABLE, region=_REGION)

        with pytest.raises(ConversationPersistenceError):
            store.get(_SESSION_ID)


def test_a_record_holding_a_foreign_session_id_is_rejected() -> None:
    with mock_aws():
        _create_table()
        boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE).put_item(
            Item={
                "dataset_id": f"ses#{_SESSION_ID}",
                "version": "CONVERSATION_CONTEXT",
                "revision": 1,
                "context": _context()
                .model_copy(update={"session_id": "ses_" + "f" * 32})
                .model_dump_json(),
            }
        )
        store = DynamoDbConversationContextStore(table_name=_TABLE, region=_REGION)

        with pytest.raises(ConversationPersistenceError):
            store.get(_SESSION_ID)


def test_a_missing_table_surfaces_as_a_persistence_error() -> None:
    with mock_aws():
        store = DynamoDbConversationContextStore(table_name="absent-table", region=_REGION)

        with pytest.raises(ConversationPersistenceError):
            store.get(_SESSION_ID)


def test_ttl_seconds_must_be_positive() -> None:
    with mock_aws(), pytest.raises(ValueError, match="ttl_seconds"):
        DynamoDbConversationContextStore(table_name=_TABLE, region=_REGION, ttl_seconds=0)
