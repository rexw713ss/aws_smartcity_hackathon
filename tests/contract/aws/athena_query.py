"""Athena QueryEngine binding for the contract suite under moto.

Moto does not execute Athena SQL (design 6.3), so this binding seeds the Moto
Athena backend with expected column metadata and rows so the adapter's
render/submit/poll/parse/error-translation path is verified.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import boto3
from moto import mock_aws

from adapters.aws.athena_query import AthenaQueryEngine
from tests.contract.registry import register_query_engine

_DATABASE = "contract_test_db"
_WORKGROUP = "primary"
_OUTPUT_BUCKET = "athena-output-bucket"
_REGION = "ap-northeast-1"
_TABLE = "fact_youth_population_monthly"


@register_query_engine("athena-moto")
@contextmanager
def _athena_query_engine() -> Iterator[AthenaQueryEngine]:
    with mock_aws():
        s3 = boto3.client("s3", region_name=_REGION)
        s3.create_bucket(
            Bucket=_OUTPUT_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": _REGION},
        )
        boto3.client("athena", region_name=_REGION)

        # Seed moto's Athena backend with column metadata and rows for the
        # allowlisted table. Moto returns these when get_query_results is called.
        # This verifies the adapter's parsing logic, not Athena's SQL engine.
        column_info = [
            {"Name": "district_code", "Type": "varchar"},
            {"Name": "youth_population", "Type": "integer"},
        ]
        rows = [
            {"Data": [{"VarCharValue": "district_code"}, {"VarCharValue": "youth_population"}]},
            {"Data": [{"VarCharValue": "01"}, {"VarCharValue": "1200"}]},
            {"Data": [{"VarCharValue": "02"}, {"VarCharValue": "3400"}]},
            {"Data": [{"VarCharValue": "03"}, {"VarCharValue": "2980"}]},
        ]

        # Patch the get_query_results to return our seeded data and
        # get_query_execution to report SUCCEEDED.
        def patched_get_results(QueryExecutionId: str, **kwargs: object) -> dict:
            return {
                "ResultSet": {
                    "ResultSetMetadata": {"ColumnInfo": column_info},
                    "Rows": rows,
                }
            }

        def patched_get_execution(QueryExecutionId: str, **kwargs: object) -> dict:
            return {
                "QueryExecution": {
                    "Status": {"State": "SUCCEEDED"},
                    "Statistics": {"DataScannedInBytes": 1024},
                }
            }

        engine = AthenaQueryEngine(
            database=_DATABASE,
            workgroup=_WORKGROUP,
            output_bucket=_OUTPUT_BUCKET,
            region=_REGION,
            allowed_tables={_TABLE},
            allowed_metrics={"youth_population"},
        )

        with (
            patch.object(engine._client, "get_query_results", side_effect=patched_get_results),
            patch.object(engine._client, "get_query_execution", side_effect=patched_get_execution),
        ):
            yield engine
