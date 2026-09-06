"""Glue+DynamoDB DataCatalog binding for the contract suite under moto."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.glue_catalog import GlueCatalog
from tests.contract.registry import register_catalog

_DATABASE = "contract_test_db"
_TABLE = "contract-catalog-metadata"
_REGION = "ap-northeast-1"


@register_catalog("glue-ddb-moto")
@contextmanager
def _glue_catalog() -> Iterator[GlueCatalog]:
    with mock_aws():
        glue = boto3.client("glue", region_name=_REGION)
        glue.create_database(DatabaseInput={"Name": _DATABASE})
        ddb = boto3.resource("dynamodb", region_name=_REGION)
        ddb.create_table(
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
        yield GlueCatalog(database=_DATABASE, table_name=_TABLE, region=_REGION)
