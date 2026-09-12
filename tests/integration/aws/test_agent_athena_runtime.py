"""AWS Agent vertical slice: published metadata -> Athena -> grounded answer."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

from adapters.aws.glue_catalog import GlueCatalog
from apps.api.dependencies import LocalRuntime
from youth_compass.agent import CopilotStatus
from youth_compass.config import (
    AppSettings,
    CatalogProvider,
    CatalogSettings,
    ForecastProvider,
    ForecastSettings,
    ModelProviderName,
    ModelSettings,
    QueryProvider,
    QuerySettings,
    StorageProvider,
    StorageSettings,
)
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)

_REGION = "us-east-1"
_DATABASE = "youth_compass_hackathon"
_METADATA_TABLE = "agent-metadata"


def _settings() -> AppSettings:
    return AppSettings(
        environment="aws",
        region=_REGION,
        storage=StorageSettings(provider=StorageProvider.S3, bucket="curated"),
        catalog=CatalogSettings(
            provider=CatalogProvider.GLUE,
            database=_DATABASE,
            table_name=_METADATA_TABLE,
        ),
        query=QuerySettings(
            provider=QueryProvider.ATHENA,
            workgroup="youth-compass-hackathon",
            output_bucket="metadata-bucket",
        ),
        model=ModelSettings(provider=ModelProviderName.OLLAMA),
        forecast=ForecastSettings(provider=ForecastProvider.LOCAL),
    )


def _metadata() -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="youth_population",
        version="v-athena-1",
        source_uri="s3://curated/youth_population/version=v-athena-1/part-000.parquet",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.98,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        published_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def _athena_client() -> MagicMock:
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "query-1"}
    client.get_query_execution.return_value = {
        "QueryExecution": {
            "Status": {"State": "SUCCEEDED"},
            "Statistics": {"DataScannedInBytes": 4096},
        }
    }
    names_and_types = [
        ("year_gregorian", "integer"),
        ("month", "integer"),
        ("city_code", "varchar"),
        ("city_name", "varchar"),
        ("district_code", "varchar"),
        ("district_name", "varchar"),
        ("metric_code", "varchar"),
        ("unit_code", "varchar"),
        ("population_scope", "varchar"),
        ("is_estimated", "boolean"),
        ("metric_value", "double"),
    ]
    rows = [
        [
            2023,
            None,
            "ntpc",
            "New Taipei",
            "banqiao",
            "Banqiao",
            "population_count",
            "persons",
            "youth_specific",
            False,
            100.0,
        ],
        [
            2025,
            None,
            "ntpc",
            "New Taipei",
            "banqiao",
            "Banqiao",
            "population_count",
            "persons",
            "youth_specific",
            False,
            120.0,
        ],
        [
            2023,
            None,
            "ntpc",
            "New Taipei",
            "linkou",
            "Linkou",
            "population_count",
            "persons",
            "youth_specific",
            False,
            80.0,
        ],
        [
            2025,
            None,
            "ntpc",
            "New Taipei",
            "linkou",
            "Linkou",
            "population_count",
            "persons",
            "youth_specific",
            False,
            72.0,
        ],
    ]

    def datum(value: object) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, bool):
            return {"VarCharValue": str(value).lower()}
        return {"VarCharValue": str(value)}

    client.get_query_results.return_value = {
        "ResultSet": {
            "ResultSetMetadata": {
                "ColumnInfo": [
                    {"Name": name, "Type": column_type} for name, column_type in names_and_types
                ]
            },
            "Rows": [
                {"Data": [{"VarCharValue": name} for name, _ in names_and_types]},
                *[{"Data": [datum(value) for value in row]} for row in rows],
            ],
        }
    }
    return client


def test_agent_answers_from_athena_rows_and_published_version(tmp_path: Path) -> None:
    with mock_aws():
        boto3.client("glue", region_name=_REGION).create_database(DatabaseInput={"Name": _DATABASE})
        boto3.resource("dynamodb", region_name=_REGION).create_table(
            TableName=_METADATA_TABLE,
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
        runtime = LocalRuntime(tmp_path, _settings())
        assert isinstance(runtime._agent_catalog, GlueCatalog)
        runtime._agent_catalog.register(_metadata())
        athena = _athena_client()

        with patch("adapters.aws.athena_query.boto3.client", return_value=athena):
            response = asyncio.run(
                runtime.copilot().answer(
                    "Compare population trend from 2023 to 2025",
                    entity_ids=("banqiao", "linkou"),
                    min_quality_score=0.9,
                )
            )

    assert response.status is CopilotStatus.ANSWERED
    assert response.observation_series is not None
    assert response.comparison is not None
    assert response.citations[0].dataset_version == "v-athena-1"
    assert response.comparison.changes[0].percent_change == 20
    assert response.comparison.changes[1].percent_change == -10
    assert any(
        trace.tool == "query_observations" and trace.outcome == "ok"
        for trace in response.tool_trace
    )
    assert athena.start_query_execution.call_count == 2
    submitted_sql = " ".join(
        call.kwargs["QueryString"] for call in athena.start_query_execution.call_args_list
    )
    assert f'FROM "{_DATABASE}"."youth_population"' in submitted_sql
