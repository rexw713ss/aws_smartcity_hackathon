"""DynamoDB ConversationContextStore binding for the contract suite under moto."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.conversation_context_store import DynamoDbConversationContextStore
from tests.contract.registry import register_conversation_store
from youth_compass.agent import ConversationContextStore

_TABLE = "contract-conversation-context"
_REGION = "us-east-1"


@register_conversation_store("dynamodb-moto")
@contextmanager
def _dynamodb_conversation_store() -> Iterator[ConversationContextStore]:
    with mock_aws():
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
        yield DynamoDbConversationContextStore(table_name=_TABLE, region=_REGION, ttl_seconds=1_800)
