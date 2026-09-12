from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapters.local import (
    DuckDBFeatureProvider,
    FeatureMaterializationConflictError,
    FeatureParquetMaterializer,
)
from youth_compass.decisioning import (
    DEFAULT_FEATURES,
    CanonicalLocation,
    FeatureEvidence,
    FeatureProvider,
    FeatureQuery,
    FeatureRegistry,
    FeatureValue,
    LocationKind,
)


def _evidence(
    dataset_id: str,
    *,
    quality_score: float = 0.9,
    retrieved_at: datetime = datetime(2026, 3, 1, tzinfo=UTC),
) -> FeatureEvidence:
    return FeatureEvidence(
        dataset_id=dataset_id,
        dataset_version="v1",
        source_uri=f"https://example.test/{dataset_id}",
        quality_score=quality_score,
        retrieved_at=retrieved_at,
    )


def _value(
    entity_id: str,
    feature_code: str,
    value: float,
    observed_at: datetime | None,
    *,
    quality_score: float = 0.9,
) -> FeatureValue:
    return FeatureValue(
        entity_id=entity_id,
        feature_code=feature_code,
        value=value,
        observed_at=observed_at,
        evidence=(_evidence(feature_code, quality_score=quality_score),),
    )


def _materialization(tmp_path: Path) -> tuple[Path, FeatureRegistry]:
    registry = FeatureRegistry(DEFAULT_FEATURES)
    destination = tmp_path / "features" / "version=v1" / "part-000.parquet"
    FeatureParquetMaterializer(registry).materialize(
        [
            _value(
                "location-a",
                "transit_accessibility",
                50,
                datetime(2026, 1, 1, tzinfo=UTC),
            ),
            _value(
                "location-a",
                "transit_accessibility",
                80,
                datetime(2026, 2, 1, tzinfo=UTC),
            ),
            _value(
                "location-b",
                "transit_accessibility",
                60,
                datetime(2026, 1, 1, tzinfo=UTC),
            ),
            _value(
                "location-a",
                "property_cost",
                500_000,
                datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        destination,
    )
    return destination, registry


def test_location_requires_coordinates_for_point_and_site() -> None:
    with pytest.raises(ValidationError, match="require coordinates"):
        CanonicalLocation(
            location_id="site:001",
            kind=LocationKind.SITE,
            display_name="Candidate site",
        )

    location = CanonicalLocation(
        location_id="site:001",
        kind=LocationKind.SITE,
        display_name="Candidate site",
        latitude=25.033,
        longitude=121.5654,
        district_code="01",
    )
    assert location.spatial_reference == "EPSG:4326"


def test_feature_materialization_is_immutable(tmp_path: Path) -> None:
    destination, registry = _materialization(tmp_path)

    with pytest.raises(FeatureMaterializationConflictError, match="already exists"):
        FeatureParquetMaterializer(registry).materialize(
            [_value("location-c", "property_cost", 100, None)],
            destination,
        )


def test_duckdb_provider_returns_latest_value_with_evidence(tmp_path: Path) -> None:
    destination, registry = _materialization(tmp_path)
    provider = DuckDBFeatureProvider(destination, registry)

    result = provider.get_features(FeatureQuery(feature_codes=("transit_accessibility",)))

    assert isinstance(provider, FeatureProvider)
    assert [(value.entity_id, value.value) for value in result.values] == [
        ("location-a", 80.0),
        ("location-b", 60.0),
    ]
    assert result.values[0].evidence[0].dataset_id == "transit_accessibility"
    assert [candidate.entity_id for candidate in result.as_candidates()] == [
        "location-a",
        "location-b",
    ]


def test_duckdb_provider_supports_as_of_and_entity_filters(tmp_path: Path) -> None:
    destination, registry = _materialization(tmp_path)
    result = DuckDBFeatureProvider(destination, registry).get_features(
        FeatureQuery(
            feature_codes=("transit_accessibility", "property_cost"),
            entity_ids=("location-a",),
            as_of=datetime(2026, 1, 15, tzinfo=UTC),
        )
    )

    assert [(value.feature_code, value.value) for value in result.values] == [
        ("property_cost", 500_000.0),
        ("transit_accessibility", 50.0),
    ]


def test_materializer_rejects_duplicate_observation_keys(tmp_path: Path) -> None:
    registry = FeatureRegistry(DEFAULT_FEATURES)
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    value = _value("location-a", "property_cost", 100, observed_at)

    with pytest.raises(ValueError, match="keys must be unique"):
        FeatureParquetMaterializer(registry).materialize(
            [value, value],
            tmp_path / "features.parquet",
        )


def test_provider_rejects_unknown_feature_before_query(tmp_path: Path) -> None:
    destination, registry = _materialization(tmp_path)

    with pytest.raises(KeyError, match="unknown feature"):
        DuckDBFeatureProvider(destination, registry).get_features(
            FeatureQuery(feature_codes=("made_up_feature",))
        )
