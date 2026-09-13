"""Offline adapters for local development and deterministic tests."""

from adapters.local.brave_search import BraveWebSearchProvider
from adapters.local.duckdb_query import DuckDBQueryEngine
from adapters.local.feature_store import (
    DuckDBFeatureProvider,
    FeatureMaterializationConflictError,
    FeatureParquetMaterializer,
)
from adapters.local.filesystem_store import FileSystemObjectStore
from adapters.local.http_source import AllowlistedHttpSourceConnector, AllowlistedLinkFetcher
from adapters.local.observation_feature_builder import (
    CanonicalObservationFeatureBuilder,
    FeatureBuildError,
)
from adapters.local.precomputed_forecast import PrecomputedParquetForecastService
from adapters.local.source_adapter import LocalTabularSourceAdapter
from adapters.local.sqlite_catalog import SQLiteCatalog
from adapters.local.sqlite_checkpoint import SQLiteCheckpointStore
from adapters.local.sqlite_feature_catalog import (
    FeatureCatalogConflictError,
    FeatureCatalogNotFoundError,
    SQLiteFeatureCatalog,
)
from adapters.local.system_clock import SystemClock

__all__ = [
    "AllowlistedHttpSourceConnector",
    "AllowlistedLinkFetcher",
    "BraveWebSearchProvider",
    "CanonicalObservationFeatureBuilder",
    "DuckDBFeatureProvider",
    "DuckDBQueryEngine",
    "FeatureBuildError",
    "FeatureCatalogConflictError",
    "FeatureCatalogNotFoundError",
    "FeatureMaterializationConflictError",
    "FeatureParquetMaterializer",
    "FileSystemObjectStore",
    "LocalTabularSourceAdapter",
    "PrecomputedParquetForecastService",
    "SQLiteCatalog",
    "SQLiteCheckpointStore",
    "SQLiteFeatureCatalog",
    "SystemClock",
]
