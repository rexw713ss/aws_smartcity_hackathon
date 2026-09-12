"""DynamoDB CheckpointStore binding for the contract suite under moto."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.dynamodb_checkpoint import DynamoDBCheckpointStore
from tests.contract.registry import register_checkpoint_store
from youth_compass.ports import CheckpointStore

_TABLE = "contract-workflow-checkpoints"
_REGION = "us-east-1"


@register_checkpoint_store("dynamodb-moto")
@contextmanager
def _dynamodb_checkpoint() -> Iterator[CheckpointStore]:
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
        yield DynamoDBCheckpointStore(table_name=_TABLE, region=_REGION)
