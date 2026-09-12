"""Local composition root for API dependencies."""

import os
from pathlib import Path

from adapters.local import (
    AllowlistedHttpSourceConnector,
    DuckDBFeatureProvider,
    DuckDBQueryEngine,
    FileSystemObjectStore,
    LocalTabularSourceAdapter,
    SQLiteCatalog,
    SQLiteCheckpointStore,
    SystemClock,
)
from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent import (
    DeterministicQueryDecomposer,
    FallbackQueryDecomposer,
    GroundedCopilotService,
    ModelAnswerComposer,
    ModelQueryDecomposer,
    ObservationToolSuite,
    default_decision_capabilities,
    register_acquisition_capabilities,
    register_observation_capabilities,
)
from youth_compass.analytics import CuratedAnalyticsService
from youth_compass.application import LocalIngestionWorkflow, LocalWorkflowOptions
from youth_compass.config import (
    AppSettings,
    CatalogProvider,
    ModelProviderName,
    QueryProvider,
    load_settings,
)
from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    DecisionProfileRegistry,
    FeatureRegistry,
)
from youth_compass.domain.canonical import CANONICAL_FIELDS
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import AnalyticsNotAvailableError, ConfigurationError
from youth_compass.ports import SourceConnector
from youth_compass.ports.catalog import DataCatalog
from youth_compass.ports.query_engine import QueryEngine


class LocalRuntime:
    """Own long-lived local adapters and construct request-scoped analytics."""

    def __init__(self, data_root: Path, settings: AppSettings | None = None) -> None:
        self.data_root = data_root.resolve()
        self.settings = settings or load_settings()
        metadata_database = self.data_root / "metadata" / "youth-compass.sqlite3"
        # The catalog is provider-selected: Glue+DynamoDB when the AWS profile is
        # active, SQLite offline. The checkpoint store stays local — it backs the
        # in-process LocalIngestionWorkflow, which the deployed API does not run
        # (uploads go through Step Functions).
        self.catalog = self._build_catalog(metadata_database)
        self.checkpoints = SQLiteCheckpointStore(metadata_database)
        self.feature_registry = FeatureRegistry(DEFAULT_FEATURES)
        self.profile_registry = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES)
        self._copilot_service: GroundedCopilotService | None = None
        self.workflow = LocalIngestionWorkflow(
            object_store=FileSystemObjectStore(self.data_root / "incoming"),
            catalog=self.catalog,
            checkpoints=self.checkpoints,
            clock=SystemClock(),
            source_adapter=LocalTabularSourceAdapter(),
            options=LocalWorkflowOptions(
                curated_root=self.data_root / "curated",
                quarantine_root=self.data_root / "quarantined",
                batch_size=self.settings.transform.batch_size,
                max_rejection_rate=self.settings.transform.max_rejection_rate,
                transformation_version=self.settings.transform.transformation_version,
            ),
        )
        connectors: tuple[SourceConnector, ...] = ()
        if self.settings.acquisition.enabled:
            connectors = (
                AllowlistedHttpSourceConnector(
                    self.settings.acquisition.connector_id,
                    self.settings.acquisition.sources,
                    allowed_hosts=frozenset(self.settings.acquisition.allowed_hosts),
                    max_download_bytes=self.settings.acquisition.max_download_bytes,
                    timeout_seconds=self.settings.acquisition.timeout_seconds,
                ),
            )
        self.acquisition = DataAcquisitionService(
            connectors,
            self.workflow,
            result_limit=self.settings.acquisition.result_limit,
        )

    def analytics(self, dataset_id: str) -> CuratedAnalyticsService:
        metadata = self.catalog.get(dataset_id)
        if metadata.status is not DatasetStatus.PUBLISHED:
            raise AnalyticsNotAvailableError(f"dataset {dataset_id!r} has no published version")
        return CuratedAnalyticsService(self._observation_query_engine(metadata), metadata)

    def _build_catalog(self, metadata_database: Path) -> DataCatalog:
        """Select the catalog by configuration: Glue on AWS, SQLite offline."""
        catalog = self.settings.catalog
        if catalog is not None and catalog.provider is CatalogProvider.GLUE:
            from adapters.aws.glue_catalog import GlueCatalog

            database = catalog.database
            table = os.environ.get("YOUTH_COMPASS_METADATA_TABLE")
            if not database or not table:
                raise ConfigurationError(
                    "the glue catalog needs catalog.database and YOUTH_COMPASS_METADATA_TABLE"
                )
            return GlueCatalog(
                database=database,
                table_name=table,
                region=os.environ.get("YOUTH_COMPASS_REGION", "us-east-1"),
            )
        return SQLiteCatalog(metadata_database)

    def _observation_query_engine(self, metadata: DatasetMetadata) -> QueryEngine:
        """Build an allowlisted engine for one immutable canonical dataset version.

        Athena over the curated S3 zone when the AWS query profile is active,
        DuckDB over the local canonical Parquet otherwise. Both enforce the same
        metric/dimension allowlist, so the analytics behaviour is identical.
        """
        allowed_metrics = {"metric_value"}
        allowed_dimensions = set(CANONICAL_FIELDS) - {"metric_value"}

        query = self.settings.query
        if query is not None and query.provider is QueryProvider.ATHENA:
            from adapters.aws.athena_query import AthenaQueryEngine

            database = self._glue_database()
            workgroup = query.workgroup
            results_bucket = os.environ.get("YOUTH_COMPASS_ATHENA_RESULTS_BUCKET")
            if not workgroup or not results_bucket:
                raise ConfigurationError(
                    "the athena query engine needs query.workgroup and "
                    "YOUTH_COMPASS_ATHENA_RESULTS_BUCKET"
                )
            # The Glue table is named by dataset_id (see the transform Lambda).
            return AthenaQueryEngine(
                database=database,
                workgroup=workgroup,
                output_bucket=results_bucket,
                region=os.environ.get("YOUTH_COMPASS_REGION", "us-east-1"),
                allowed_tables={metadata.dataset_id},
                allowed_metrics=allowed_metrics,
                allowed_dimensions=allowed_dimensions,
            )

        parquet = (
            self.data_root
            / "curated"
            / metadata.dataset_id
            / f"version={metadata.version}"
            / "part-000.parquet"
        )
        return DuckDBQueryEngine(
            tables={metadata.dataset_id: parquet},
            allowed_metrics=allowed_metrics,
            allowed_dimensions=allowed_dimensions,
        )

    def _glue_database(self) -> str:
        catalog = self.settings.catalog
        if catalog is None or not catalog.database:
            raise ConfigurationError("query.provider=athena requires catalog.database")
        return catalog.database

    def copilot(self) -> GroundedCopilotService:
        """Build the offline agent over the current immutable feature snapshot."""

        if self._copilot_service is not None:
            return self._copilot_service
        decomposer = None
        answer_composer = None
        if self.settings.model and self.settings.model.provider is ModelProviderName.BEDROCK:
            from adapters.aws.bedrock_model import BedrockModelProvider

            model_id = self.settings.model.model_id
            if not model_id or model_id.startswith("<PLACEHOLDER_"):
                raise ConfigurationError(
                    "model.model_id is required when the Bedrock provider is selected"
                )
            bedrock = BedrockModelProvider(
                model_id,
                region=self.settings.model.region,
                timeout_seconds=self.settings.model.timeout_seconds,
                max_attempts=self.settings.model.max_attempts,
            )
            if self.settings.model.decompose_queries:
                # The decomposer describes operations using the same registry the
                # router will search, so the prompt cannot drift from reality.
                capabilities = default_decision_capabilities()
                register_observation_capabilities(capabilities)
                register_acquisition_capabilities(capabilities)
                decomposer = FallbackQueryDecomposer(
                    ModelQueryDecomposer(bedrock, capabilities), DeterministicQueryDecomposer()
                )
            if self.settings.model.compose_answers:
                answer_composer = ModelAnswerComposer(bedrock)
        provider = DuckDBFeatureProvider(
            self.data_root / "features" / "current.parquet",
            self.feature_registry,
        )
        self._copilot_service = GroundedCopilotService(
            feature_provider=provider,
            feature_registry=self.feature_registry,
            profile_registry=self.profile_registry,
            decomposer=decomposer,
            answer_composer=answer_composer,
            observation_tools=ObservationToolSuite(self.catalog, self._observation_query_engine),
            acquisition=self.acquisition,
        )
        return self._copilot_service
