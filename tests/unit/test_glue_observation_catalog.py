"""Published dataset projection used by the AWS Agent observation tools."""

from datetime import UTC, datetime

import boto3
from moto import mock_aws

from adapters.aws.glue_catalog import GlueCatalog
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)

_DATABASE = "agent_catalog"
_TABLE = "agent-metadata"
_REGION = "us-east-1"


def _metadata(version: str, status: DatasetStatus) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="population",
        version=version,
        source_uri=f"s3://curated/population/version={version}/part-000.parquet",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=status,
        quality_score=0.95,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        published_at=(
            datetime(2026, 9, 12, tzinfo=UTC) if status is DatasetStatus.PUBLISHED else None
        ),
    )


def test_list_datasets_returns_only_the_published_pointer_version() -> None:
    with mock_aws():
        boto3.client("glue", region_name=_REGION).create_database(DatabaseInput={"Name": _DATABASE})
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
        catalog = GlueCatalog(_DATABASE, _TABLE, _REGION)
        published = _metadata("v1", DatasetStatus.PUBLISHED)
        catalog.register(published)
        catalog.register(_metadata("v2", DatasetStatus.QUARANTINED))

        assert catalog.list_datasets() == [published]
        assert catalog.get("population") == published
