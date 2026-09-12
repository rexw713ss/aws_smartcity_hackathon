"""GlueCatalog listing backs the API's /datasets endpoints.

Feature: real-data analytics loop. The API's catalog-listing routes call
list_datasets/list_versions, which previously existed only on SQLiteCatalog;
the deployed API uses GlueCatalog, so these must work there too.
"""

from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from adapters.aws.glue_catalog import GlueCatalog
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)

REGION = "us-east-1"
DATABASE = "youth_compass_test"
TABLE = "youthcompass-metadata"


def _metadata(dataset_id: str, version: str, *, created: datetime) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id=dataset_id,
        version=version,
        source_uri=f"s3://incoming/{dataset_id}.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.GENERAL_POPULATION,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.98,
        created_at=created,
    )


@pytest.fixture
def _catalog():
    with mock_aws():
        boto3.resource("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
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
        boto3.client("glue", region_name=REGION).create_database(DatabaseInput={"Name": DATABASE})
        yield GlueCatalog(database=DATABASE, table_name=TABLE, region=REGION)


class TestGlueCatalogListing:
    def test_list_datasets_returns_one_published_record_per_dataset(
        self, _catalog: GlueCatalog
    ) -> None:
        _catalog.register(_metadata("pop_a", "v1", created=datetime(2026, 1, 1, tzinfo=UTC)))
        _catalog.register(_metadata("pop_b", "v1", created=datetime(2026, 1, 2, tzinfo=UTC)))

        listed = _catalog.list_datasets()

        assert [record.dataset_id for record in listed] == ["pop_a", "pop_b"]

    def test_list_versions_returns_history_oldest_first(self, _catalog: GlueCatalog) -> None:
        _catalog.register(_metadata("pop_a", "v1", created=datetime(2026, 1, 1, tzinfo=UTC)))
        _catalog.register(_metadata("pop_a", "v2", created=datetime(2026, 2, 1, tzinfo=UTC)))

        versions = _catalog.list_versions("pop_a")

        assert [record.version for record in versions] == ["v1", "v2"]

    def test_listing_is_empty_before_anything_is_registered(self, _catalog: GlueCatalog) -> None:
        assert _catalog.list_datasets() == []
        assert _catalog.list_versions("pop_a") == []
