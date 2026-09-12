"""The API composition root selects Glue+Athena when the AWS profile is active.

Feature: real-data analytics loop. LocalRuntime stays SQLite+DuckDB offline, but
under an AWS profile (catalog: glue, query: athena) it must build the boto3
adapters and pass their required configuration.
"""

from pathlib import Path

import pytest

from adapters.aws.athena_query import AthenaQueryEngine
from adapters.aws.glue_catalog import GlueCatalog
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
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)
from youth_compass.domain.errors import ConfigurationError


def _aws_settings() -> AppSettings:
    # A non-local environment must supply every provider key.
    return AppSettings(
        environment="aws",
        storage=StorageSettings(provider=StorageProvider.S3, bucket="curated-bkt"),
        catalog=CatalogSettings(provider=CatalogProvider.GLUE, database="youth_compass_test"),
        query=QuerySettings(provider=QueryProvider.ATHENA, workgroup="wg-analytics"),
        model=ModelSettings(provider=ModelProviderName.BEDROCK, model_id="amazon.nova-lite-v1:0"),
        forecast=ForecastSettings(provider=ForecastProvider.LOCAL),
    )


def _published(dataset_id: str = "population") -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id=dataset_id,
        version="v1",
        source_uri="s3://incoming/pop.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian"]),
        population_scope=PopulationScope.GENERAL_POPULATION,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.98,
    )


class TestAwsAnalyticsWiring:
    def test_glue_catalog_is_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_METADATA_TABLE", "youthcompass-metadata")
        monkeypatch.setenv("YOUTH_COMPASS_REGION", "us-east-1")

        runtime = LocalRuntime(tmp_path / "data", settings=_aws_settings())

        assert isinstance(runtime.catalog, GlueCatalog)

    def test_athena_engine_is_built_for_a_published_dataset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_METADATA_TABLE", "youthcompass-metadata")
        monkeypatch.setenv("YOUTH_COMPASS_ATHENA_RESULTS_BUCKET", "youthcompass-metadata-bkt")
        monkeypatch.setenv("YOUTH_COMPASS_REGION", "us-east-1")
        runtime = LocalRuntime(tmp_path / "data", settings=_aws_settings())

        engine = runtime._observation_query_engine(_published())

        assert isinstance(engine, AthenaQueryEngine)

    def test_athena_without_a_results_bucket_is_a_configuration_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_METADATA_TABLE", "youthcompass-metadata")
        monkeypatch.delenv("YOUTH_COMPASS_ATHENA_RESULTS_BUCKET", raising=False)
        runtime = LocalRuntime(tmp_path / "data", settings=_aws_settings())

        with pytest.raises(ConfigurationError, match=r"(?i)results_bucket"):
            runtime._observation_query_engine(_published())

    def test_local_profile_still_uses_duckdb_and_sqlite(self, tmp_path: Path) -> None:
        from adapters.local import DuckDBQueryEngine, SQLiteCatalog

        runtime = LocalRuntime(tmp_path / "data", settings=AppSettings(environment="local"))

        assert isinstance(runtime.catalog, SQLiteCatalog)
        engine = runtime._observation_query_engine(_published())
        assert isinstance(engine, DuckDBQueryEngine)
