"""Composition-root selection for Athena-backed Agent observations."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.aws.athena_query import AthenaQueryEngine
from adapters.aws.glue_catalog import GlueCatalog
from adapters.local import DuckDBQueryEngine, SQLiteCatalog
from apps.api.dependencies import LocalRuntime
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
from youth_compass.domain import ConfigurationError
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)


def _settings(*, query_provider: str = "athena") -> AppSettings:
    return AppSettings(
        environment="aws",
        region="us-east-1",
        storage=StorageSettings(provider=StorageProvider.S3, bucket="curated"),
        catalog=CatalogSettings(
            provider=CatalogProvider.GLUE,
            database="youth_compass_hackathon",
            table_name="metadata-table",
        ),
        query=QuerySettings(
            provider=QueryProvider(query_provider),
            workgroup="youth-compass-hackathon",
            output_bucket="metadata-bucket",
        ),
        model=ModelSettings(provider=ModelProviderName.OLLAMA),
        forecast=ForecastSettings(provider=ForecastProvider.LOCAL),
    )


def _metadata() -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="population",
        version="v1",
        source_uri="s3://curated/population/version=v1/part-000.parquet",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=1,
    )


def test_aws_runtime_wires_glue_catalog_and_athena_factory(tmp_path: Path) -> None:
    with (
        patch("adapters.aws.glue_catalog.boto3.client", return_value=MagicMock()),
        patch("adapters.aws.glue_catalog.boto3.resource", return_value=MagicMock()),
        patch("adapters.aws.athena_query.boto3.client", return_value=MagicMock()),
    ):
        runtime = LocalRuntime(tmp_path, _settings())
        engine = runtime._agent_query_engine_factory(_metadata())

    # Under the AWS profile the catalog is Glue for both the dashboard's
    # analytics()/list_datasets and the agent's observation tools, so both read
    # the same published catalog. (Before the analytics-loop merge the main
    # catalog stayed SQLite; the dashboard then read an empty local store.)
    assert isinstance(runtime.catalog, GlueCatalog)
    assert isinstance(runtime._agent_catalog, GlueCatalog)
    assert isinstance(engine, AthenaQueryEngine)


def test_local_runtime_keeps_duckdb_observation_factory(tmp_path: Path) -> None:
    runtime = LocalRuntime(tmp_path, AppSettings())
    metadata = _metadata().model_copy(
        update={"source_uri": "file:///curated/population/part-000.parquet"}
    )

    engine = runtime._agent_query_engine_factory(metadata)

    assert isinstance(runtime._agent_catalog, SQLiteCatalog)
    assert isinstance(engine, DuckDBQueryEngine)


def test_mixed_glue_and_duckdb_configuration_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Glue and Athena together"):
        LocalRuntime(tmp_path, _settings(query_provider="duckdb"))
