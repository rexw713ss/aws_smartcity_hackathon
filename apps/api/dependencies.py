"""Local composition root for API dependencies."""

from pathlib import Path

from adapters.local import (
    DuckDBFeatureProvider,
    DuckDBQueryEngine,
    FileSystemObjectStore,
    LocalTabularSourceAdapter,
    SQLiteCatalog,
    SQLiteCheckpointStore,
    SystemClock,
)
from youth_compass.agent import (
    DeterministicQueryDecomposer,
    FallbackQueryDecomposer,
    GroundedCopilotService,
    ModelQueryDecomposer,
    ObservationToolSuite,
)
from youth_compass.analytics import CuratedAnalyticsService
from youth_compass.application import LocalIngestionWorkflow, LocalWorkflowOptions
from youth_compass.config import AppSettings, ModelProviderName, load_settings
from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    DecisionProfileRegistry,
    FeatureRegistry,
)
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import AnalyticsNotAvailableError, ConfigurationError
from youth_compass.transformation.schema import CANONICAL_FIELDS


class LocalRuntime:
    """Own long-lived local adapters and construct request-scoped analytics."""

    def __init__(self, data_root: Path, settings: AppSettings | None = None) -> None:
        self.data_root = data_root.resolve()
        self.settings = settings or load_settings()
        metadata_database = self.data_root / "metadata" / "youth-compass.sqlite3"
        self.catalog = SQLiteCatalog(metadata_database)
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

    def analytics(self, dataset_id: str) -> CuratedAnalyticsService:
        metadata = self.catalog.get(dataset_id)
        if metadata.status is not DatasetStatus.PUBLISHED:
            raise AnalyticsNotAvailableError(f"dataset {dataset_id!r} has no published version")
        return CuratedAnalyticsService(self._observation_query_engine(metadata), metadata)

    def _observation_query_engine(self, metadata: DatasetMetadata) -> DuckDBQueryEngine:
        """Build an allowlisted engine for one immutable canonical dataset version."""

        parquet = (
            self.data_root
            / "curated"
            / metadata.dataset_id
            / f"version={metadata.version}"
            / "part-000.parquet"
        )
        return DuckDBQueryEngine(
            tables={metadata.dataset_id: parquet},
            allowed_metrics={"metric_value"},
            allowed_dimensions=set(CANONICAL_FIELDS) - {"metric_value"},
        )

    def copilot(self) -> GroundedCopilotService:
        """Build the offline agent over the current immutable feature snapshot."""

        if self._copilot_service is not None:
            return self._copilot_service
        decomposer = None
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
            decomposer = FallbackQueryDecomposer(
                ModelQueryDecomposer(bedrock), DeterministicQueryDecomposer()
            )
        provider = DuckDBFeatureProvider(
            self.data_root / "features" / "current.parquet",
            self.feature_registry,
        )
        self._copilot_service = GroundedCopilotService(
            feature_provider=provider,
            feature_registry=self.feature_registry,
            profile_registry=self.profile_registry,
            decomposer=decomposer,
            observation_tools=ObservationToolSuite(
                self.catalog, self._observation_query_engine
            ),
        )
        return self._copilot_service
