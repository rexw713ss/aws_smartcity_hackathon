"""Curated publish registers a real Glue table; rejection registers nothing.

Feature: aws-stage2-adapters (PR2). Closes the Definition-of-Done item
"approval produces real curated objects and a Glue table": the transform step
previously copied the object to the curated zone without ever registering it,
so the published data was not queryable.
"""

import boto3
import pytest
from moto import mock_aws

from adapters.aws.transform_lambda import handler

REGION = "us-east-1"
INCOMING = "incoming-bucket"
CURATED = "curated-bucket"
QUARANTINED = "quarantined-bucket"
DATABASE = "youth_compass_test"

CSV = "year,district,age_label,count\n2024,Banqiao,15-19,1200\n2024,Xinzhuang,20-24,980\n"


@pytest.fixture
def _aws(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
    monkeypatch.setenv("YOUTH_COMPASS_CURATED_BUCKET", CURATED)
    monkeypatch.setenv("YOUTH_COMPASS_QUARANTINED_BUCKET", QUARANTINED)
    monkeypatch.setenv("YOUTH_COMPASS_GLUE_DATABASE", DATABASE)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        for bucket in (INCOMING, CURATED, QUARANTINED):
            s3.create_bucket(Bucket=bucket)
        s3.put_object(Bucket=INCOMING, Key="incoming/job-1/youth.csv", Body=CSV.encode())
        boto3.client("glue", region_name=REGION).create_database(DatabaseInput={"Name": DATABASE})
        yield


def _event(approved: bool, job_id: str = "job-1") -> dict[str, object]:
    return {
        "action": "transform",
        "approved": approved,
        "job_id": job_id,
        "source_uri": f"s3://{INCOMING}/incoming/job-1/youth.csv",
    }


class TestCuratedPublishRegistersGlueTable:
    def test_approval_writes_curated_object_and_registers_the_table(self, _aws: None) -> None:
        result = handler(_event(approved=True), None)

        assert result["status"] == "ok"
        assert result["published"] is True
        assert result["glue_table"] == f"{DATABASE}.job_1"

        # The curated object exists.
        curated = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=CURATED)
        assert [obj["Key"] for obj in curated["Contents"]] == ["curated/job-1/youth.csv"]

        # The Glue table describes the curated location with the real schema.
        table = boto3.client("glue", region_name=REGION).get_table(
            DatabaseName=DATABASE, Name="job_1"
        )["Table"]
        descriptor = table["StorageDescriptor"]
        assert descriptor["Location"] == f"s3://{CURATED}/curated/job-1/"
        assert [column["Name"] for column in descriptor["Columns"]] == [
            "year",
            "district",
            "age_label",
            "count",
        ]
        # Types come from the profiler, not a placeholder.
        types = {column["Name"]: column["Type"] for column in descriptor["Columns"]}
        assert types["year"] == "bigint"
        assert types["count"] == "bigint"
        assert types["district"] == "string"
        # The CSV header must not surface as a data row in Athena.
        assert table["Parameters"]["skip.header.line.count"] == "1"

    def test_rejection_quarantines_without_registering_a_table(self, _aws: None) -> None:
        result = handler(_event(approved=False), None)

        assert result["status"] == "ok"
        assert result["published"] is False
        assert result["glue_table"] is None

        quarantined = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=QUARANTINED)
        assert [obj["Key"] for obj in quarantined["Contents"]] == ["quarantined/job-1/youth.csv"]

        # Nothing was published to curated, and no table exists.
        assert "Contents" not in boto3.client("s3", region_name=REGION).list_objects_v2(
            Bucket=CURATED
        )
        tables = boto3.client("glue", region_name=REGION).get_tables(DatabaseName=DATABASE)
        assert tables["TableList"] == []

    def test_republishing_the_same_job_updates_rather_than_failing(self, _aws: None) -> None:
        first = handler(_event(approved=True), None)
        second = handler(_event(approved=True), None)

        assert first["glue_table"] == second["glue_table"]
        # Exactly one table, carrying the later schema.
        tables = boto3.client("glue", region_name=REGION).get_tables(DatabaseName=DATABASE)
        assert [table["Name"] for table in tables["TableList"]] == ["job_1"]

    def test_absent_glue_database_skips_registration(
        self, _aws: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Local and Moto runs that do not configure Glue must still publish.
        monkeypatch.delenv("YOUTH_COMPASS_GLUE_DATABASE")

        result = handler(_event(approved=True), None)

        assert result["published"] is True
        assert result["glue_table"] is None
