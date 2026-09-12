"""The API composition root selects Glue+Athena for the dashboard read path.

Feature: real-data analytics loop. A teammate's test_aws_agent_runtime.py covers
the *agent* observation backend; this covers the *dashboard* path — the catalog
and analytics() query engine — so /datasets, /city/summary, and /districts read
the published data through Glue+Athena when the AWS profile is active, and stay
on SQLite+DuckDB offline.
"""

from pathlib import Path

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
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)


def _aws_settings() -> AppSettings:
    # A non-local environment must supply every provider key.
    return AppSettings(
        environment="aws",
        region="us-east-1",
        storage=StorageSettings(provider=StorageProvider.S3, bucket="curated-bkt"),
        catalog=CatalogSettings(
            provider=CatalogProvider.GLUE,
            database="youth_compass_test",
            table_name="metadata-table",
        ),
        query=QuerySettings(
            provider=QueryProvider.ATHENA,
            workgroup="wg-analytics",
            output_bucket="metadata-bkt",
        ),
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


class TestDashboardAnalyticsWiring:
    def test_catalog_is_glue_under_the_aws_profile(self, tmp_path: Path) -> None:
        runtime = LocalRuntime(tmp_path / "data", settings=_aws_settings())

        assert isinstance(runtime.catalog, GlueCatalog)

    def test_dashboard_query_engine_is_athena_under_the_aws_profile(self, tmp_path: Path) -> None:
        runtime = LocalRuntime(tmp_path / "data", settings=_aws_settings())

        engine = runtime._observation_query_engine(_published())

        assert isinstance(engine, AthenaQueryEngine)

    def test_local_profile_stays_on_sqlite_and_duckdb(self, tmp_path: Path) -> None:
        runtime = LocalRuntime(tmp_path / "data", settings=AppSettings(environment="local"))

        assert isinstance(runtime.catalog, SQLiteCatalog)
        assert isinstance(runtime._observation_query_engine(_published()), DuckDBQueryEngine)
