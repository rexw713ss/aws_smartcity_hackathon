"""The transform Lambda publishes canonical Parquet and a typed Glue table.

Feature: real-data analytics loop. Replaces the earlier behaviour where the
approved path copied the raw CSV and registered a source-derived, CSV-shaped
Glue table. Now the approved path runs the real row transform, writes canonical
Parquet to a versioned curated layout, registers a Parquet Glue table with the
canonical schema, and records the published dataset in DynamoDB so the API
catalog can resolve it.
"""

import io

import boto3
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

from adapters.aws.transform_lambda import handler
from youth_compass.domain.canonical import CANONICAL_FIELDS

REGION = "us-east-1"
INCOMING = "incoming-bucket"
CURATED = "curated-bucket"
QUARANTINED = "quarantined-bucket"
DATABASE = "youth_compass_test"
METADATA_TABLE = "youthcompass-metadata"

# A population source the mapping engine understands with high confidence.
POPULATION_CSV = (
    "year,district,age,population\n"
    "2023,板橋區,20-24,47100\n"
    "2024,板橋區,20-24,47800\n"
    "2025,板橋區,20-24,48200\n"
    "2023,新莊區,20-24,40230\n"
    "2024,新莊區,20-24,41010\n"
    "2025,新莊區,20-24,41720\n"
).encode()


@pytest.fixture
def _aws(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
    monkeypatch.setenv("YOUTH_COMPASS_CURATED_BUCKET", CURATED)
    monkeypatch.setenv("YOUTH_COMPASS_QUARANTINED_BUCKET", QUARANTINED)
    monkeypatch.setenv("YOUTH_COMPASS_GLUE_DATABASE", DATABASE)
    monkeypatch.setenv("YOUTH_COMPASS_METADATA_TABLE", METADATA_TABLE)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        for bucket in (INCOMING, CURATED, QUARANTINED):
            s3.create_bucket(Bucket=bucket)
        s3.put_object(Bucket=INCOMING, Key="incoming/job-pop/population.csv", Body=POPULATION_CSV)
        boto3.client("glue", region_name=REGION).create_database(DatabaseInput={"Name": DATABASE})
        boto3.resource("dynamodb", region_name=REGION).create_table(
            TableName=METADATA_TABLE,
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
        yield


def _transform_event(approved: bool = True) -> dict[str, object]:
    return {
        "action": "transform",
        "approved": approved,
        "job_id": "job-pop",
        "source_uri": f"s3://{INCOMING}/incoming/job-pop/population.csv",
        "decided_by": "reviewer@example.org",
    }


class TestCanonicalPublish:
    def test_publishes_canonical_parquet_to_the_versioned_layout(self, _aws: None) -> None:
        result = handler(_transform_event(), None)

        assert result["status"] == "ok"
        assert result["published"] is True
        dataset_id = result["dataset_id"]
        dataset_version = result["dataset_version"]

        # Object lands at curated/{dataset_id}/version={version}/part-000.parquet.
        expected_key = f"curated/{dataset_id}/version={dataset_version}/part-000.parquet"
        assert result["uri"] == f"s3://{CURATED}/{expected_key}"
        stored = boto3.client("s3", region_name=REGION).get_object(Bucket=CURATED, Key=expected_key)
        body = stored["Body"].read()

        # It is real Parquet with the canonical schema and real rows.
        table = pq.read_table(io.BytesIO(body))
        assert tuple(table.schema.names) == CANONICAL_FIELDS
        assert table.num_rows == result["observation_count"] > 0
        years = set(table.column("year_gregorian").to_pylist())
        assert {2023, 2024, 2025}.issubset(years)

    def test_registers_a_typed_parquet_glue_table(self, _aws: None) -> None:
        result = handler(_transform_event(), None)
        dataset_id = result["dataset_id"]

        table = boto3.client("glue", region_name=REGION).get_table(
            DatabaseName=DATABASE, Name=dataset_id
        )["Table"]
        descriptor = table["StorageDescriptor"]

        # Canonical schema, not source columns.
        assert tuple(col["Name"] for col in descriptor["Columns"]) == CANONICAL_FIELDS
        types = {col["Name"]: col["Type"] for col in descriptor["Columns"]}
        assert types["year_gregorian"] == "smallint"
        assert types["metric_value"] == "double"
        assert types["is_estimated"] == "boolean"
        # Parquet SerDe, not the old CSV LazySimpleSerDe.
        assert "parquet" in descriptor["SerdeInfo"]["SerializationLibrary"].lower()
        assert table["Parameters"]["classification"] == "parquet"
        assert table["Parameters"]["youth_compass_dataset_version"] == result["dataset_version"]
        # Location is the version prefix, not a per-job folder.
        assert descriptor["Location"].endswith(
            f"/{dataset_id}/version={result['dataset_version']}/"
        )

    def test_records_published_metadata_for_the_api_catalog(self, _aws: None) -> None:
        result = handler(_transform_event(), None)
        dataset_id = result["dataset_id"]

        table = boto3.resource("dynamodb", region_name=REGION).Table(METADATA_TABLE)
        pointer = table.get_item(Key={"dataset_id": dataset_id, "version": "__published__"})["Item"]
        assert pointer["published_version"] == result["dataset_version"]

        record = table.get_item(
            Key={"dataset_id": dataset_id, "version": result["dataset_version"]}
        )["Item"]
        assert record["status"] == "published"

    def test_rejection_quarantines_and_registers_nothing(self, _aws: None) -> None:
        result = handler(_transform_event(approved=False), None)

        assert result["published"] is False
        assert result["glue_table"] is None
        assert result["uri"].startswith(f"s3://{QUARANTINED}/quarantined/job-pop/")
        # No curated object, no Glue table, no published pointer.
        assert "Contents" not in boto3.client("s3", region_name=REGION).list_objects_v2(
            Bucket=CURATED
        )
        assert (
            boto3.client("glue", region_name=REGION).get_tables(DatabaseName=DATABASE)["TableList"]
            == []
        )

    def test_republishing_the_same_source_is_idempotent(self, _aws: None) -> None:
        first = handler(_transform_event(), None)
        second = handler(_transform_event(), None)

        # Content-addressed version: same input, same version, one Glue table.
        assert first["dataset_version"] == second["dataset_version"]
        tables = boto3.client("glue", region_name=REGION).get_tables(DatabaseName=DATABASE)[
            "TableList"
        ]
        assert len(tables) == 1
