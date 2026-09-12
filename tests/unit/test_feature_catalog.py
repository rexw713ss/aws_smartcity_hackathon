from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters.local import (
    FeatureCatalogConflictError,
    FeatureCatalogNotFoundError,
    SQLiteFeatureCatalog,
)
from youth_compass.decisioning import (
    DEFAULT_FEATURES,
    EntityType,
    FeatureDefinition,
    FeatureMaterializationMetadata,
    FeatureMaterializationStatus,
    FeatureRegistry,
    FeatureSearchQuery,
    SemanticFeatureCatalog,
)


def _materialization(
    *,
    version: str = "snapshot-v1",
    status: FeatureMaterializationStatus = FeatureMaterializationStatus.PUBLISHED,
    quality_score: float = 0.9,
) -> FeatureMaterializationMetadata:
    return FeatureMaterializationMetadata(
        feature_code="transit_accessibility",
        feature_version="v1",
        materialization_version=version,
        storage_uri=f"data/features/transit/version={version}/part-000.parquet",
        source_datasets=("mrt_stations@v1", "bus_stops@v2"),
        entity_count=100,
        spatial_grain="h3_9",
        temporal_grain="month",
        observed_from=datetime(2026, 1, 1, tzinfo=UTC),
        observed_to=datetime(2026, 3, 1, tzinfo=UTC),
        materialized_at=datetime(2026, 3, 2, tzinfo=UTC),
        fresh_until=datetime(2026, 4, 2, tzinfo=UTC),
        quality_score=quality_score,
        supported_filters=("entity_id", "observed_at"),
        status=status,
    )


def _catalog(tmp_path: Path) -> SQLiteFeatureCatalog:
    return SQLiteFeatureCatalog(
        tmp_path / "feature-catalog.sqlite3", FeatureRegistry(DEFAULT_FEATURES)
    )


def test_feature_registry_supports_immutable_versions() -> None:
    original = DEFAULT_FEATURES[0]
    second = FeatureDefinition.model_validate(
        {**original.model_dump(), "version": "v2", "description": "Second contract version."}
    )
    registry = FeatureRegistry((original, second))

    assert registry.get(original.feature_code).version == "v2"
    assert registry.get(original.feature_code, "v1") == original
    assert len(registry.list()) == 2


def test_catalog_only_advances_pointer_for_published_materialization(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    published = _materialization()
    draft = _materialization(version="snapshot-v2", status=FeatureMaterializationStatus.DRAFT)
    catalog.register(published)
    catalog.register(draft)

    assert isinstance(catalog, SemanticFeatureCatalog)
    assert catalog.get("transit_accessibility").materialization == published
    assert catalog.get("transit_accessibility", "snapshot-v2").materialization == draft


def test_catalog_persists_and_searches_semantics_and_coverage(tmp_path: Path) -> None:
    database = tmp_path / "feature-catalog.sqlite3"
    registry = FeatureRegistry(DEFAULT_FEATURES)
    SQLiteFeatureCatalog(database, registry).register(_materialization())
    restarted = SQLiteFeatureCatalog(database, registry)

    matches = restarted.search(
        FeatureSearchQuery(
            text="commute",
            entity_type=EntityType.LOCATION,
            spatial_grains=("h3_9",),
            temporal_grains=("month",),
            required_filters=("entity_id",),
            min_quality_score=0.85,
            observed_at=datetime(2026, 2, 1, tzinfo=UTC),
            fresh_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )

    assert [entry.definition.feature_code for entry in matches] == ["transit_accessibility"]
    assert restarted.search(FeatureSearchQuery(text="unrelated capability")) == ()
    assert restarted.search(FeatureSearchQuery(fresh_at=datetime(2026, 5, 1, tzinfo=UTC))) == ()


def test_catalog_rejects_conflicting_immutable_metadata(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog.register(_materialization())

    with pytest.raises(FeatureCatalogConflictError, match="conflicts"):
        catalog.register(_materialization(quality_score=0.8))


def test_catalog_rejects_definition_grain_mismatch(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    invalid = _materialization().model_copy(update={"spatial_grain": "district"})

    with pytest.raises(FeatureCatalogConflictError, match="spatial grain"):
        catalog.register(invalid)


def test_catalog_get_requires_published_pointer_by_default(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog.register(_materialization(status=FeatureMaterializationStatus.DRAFT))

    with pytest.raises(FeatureCatalogNotFoundError):
        catalog.get("transit_accessibility")
