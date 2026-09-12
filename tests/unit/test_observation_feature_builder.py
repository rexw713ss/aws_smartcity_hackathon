from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from adapters.local import (
    CanonicalObservationFeatureBuilder,
    DuckDBFeatureProvider,
    FeatureBuildError,
    FeatureParquetMaterializer,
)
from youth_compass.decisioning import (
    CandidateFeatures,
    DecisionCriterion,
    DecisionProfile,
    DecisionScoringEngine,
    EntityType,
    FeatureAggregation,
    FeatureDefinition,
    FeatureQuery,
    FeatureRegistry,
    LocationResolutionMethod,
    NewTaipeiDistrictResolver,
    ObservationFeatureBuildSpec,
    OptimizationDirection,
)
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)


def _registry() -> FeatureRegistry:
    return FeatureRegistry(
        [
            FeatureDefinition(
                feature_code="population_total",
                display_name="Population total",
                description="Published population aggregated at district grain.",
                entity_type=EntityType.LOCATION,
                unit_code="persons",
                spatial_grain="district",
                temporal_grain="month",
                aggregation_method="sum",
                source_metric_codes=("population_count",),
                valid_min=0,
            )
        ]
    )


def _metadata(status: DatasetStatus = DatasetStatus.PUBLISHED) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="population",
        version="v1",
        source_uri="https://example.test/population.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "month", "district_code"]),
        population_scope=PopulationScope.GENERAL_POPULATION,
        status=status,
        quality_score=0.95,
        mapping_version="mapping-v1",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        published_at=(
            datetime(2026, 3, 2, tzinfo=UTC) if status is DatasetStatus.PUBLISHED else None
        ),
    )


def _observations(tmp_path: Path, *, mixed_units: bool = False) -> Path:
    path = tmp_path / "canonical.parquet"
    pq.write_table(
        pa.table(
            {
                "dataset_id": ["population"] * 4,
                "dataset_version": ["v1"] * 4,
                "year_gregorian": [2025, 2026, 2026, 2026],
                "month": [1, 1, 1, 1],
                "district_code": ["01", "01", "01", "02"],
                "metric_code": ["population_count"] * 4,
                "metric_value": [999.0, 10.0, 20.0, 5.0],
                "unit_code": [
                    "persons",
                    "persons",
                    "households" if mixed_units else "persons",
                    "persons",
                ],
                "population_scope": ["general_population"] * 4,
            }
        ),
        path,
    )
    return path


def test_district_resolver_returns_stable_location_identity() -> None:
    resolver = NewTaipeiDistrictResolver()
    alias = resolver.resolve("新北市板橋區")
    exact = resolver.resolve("district:65000:01")

    assert len(resolver.list_locations()) == 29
    assert alias.location is not None
    assert alias.location.location_id == "district:65000:01"
    assert alias.method is LocationResolutionMethod.DISTRICT_ALIAS
    assert exact.location == alias.location
    assert exact.method is LocationResolutionMethod.EXACT_ID
    assert resolver.resolve("unknown").location is None


def test_builder_uses_latest_period_and_aggregates_by_canonical_location(
    tmp_path: Path,
) -> None:
    registry = _registry()
    values = CanonicalObservationFeatureBuilder(registry).build(
        _observations(tmp_path),
        _metadata(),
        ObservationFeatureBuildSpec(
            feature_code="population_total",
            source_metric_code="population_count",
            aggregation=FeatureAggregation.SUM,
        ),
    )

    assert [(value.entity_id, value.value) for value in values] == [
        ("district:65000:01", 30.0),
        ("district:65000:02", 5.0),
    ]
    assert all(value.observed_at == datetime(2026, 1, 1, tzinfo=UTC) for value in values)
    assert values[0].evidence[0].dataset_version == "v1"


def test_builder_provider_and_scorer_form_an_end_to_end_slice(tmp_path: Path) -> None:
    registry = _registry()
    values = CanonicalObservationFeatureBuilder(registry).build(
        _observations(tmp_path),
        _metadata(),
        ObservationFeatureBuildSpec(
            feature_code="population_total",
            source_metric_code="population_count",
            aggregation=FeatureAggregation.SUM,
        ),
    )
    materialized = FeatureParquetMaterializer(registry).materialize(
        values,
        tmp_path / "features" / "version=v1" / "part-000.parquet",
    )
    candidates: tuple[CandidateFeatures, ...] = (
        DuckDBFeatureProvider(materialized, registry)
        .get_features(FeatureQuery(feature_codes=("population_total",)))
        .as_candidates()
    )
    profile = DecisionProfile(
        profile_code="population_priority",
        version="v1",
        display_name="Population priority",
        candidate_type="district",
        criteria=(
            DecisionCriterion(
                feature_code="population_total",
                weight=1,
                direction=OptimizationDirection.MAXIMIZE,
            ),
        ),
    )

    result = DecisionScoringEngine(registry).score(profile, candidates)

    assert [(item.entity_id, item.score) for item in result.candidates] == [
        ("district:65000:01", 100.0),
        ("district:65000:02", 0.0),
    ]
    assert result.candidates[0].contributions[0].evidence[0].quality_score == 0.95


def test_builder_rejects_unpublished_dataset(tmp_path: Path) -> None:
    with pytest.raises(FeatureBuildError, match="published dataset"):
        CanonicalObservationFeatureBuilder(_registry()).build(
            _observations(tmp_path),
            _metadata(DatasetStatus.QUARANTINED),
            ObservationFeatureBuildSpec(
                feature_code="population_total",
                source_metric_code="population_count",
                aggregation=FeatureAggregation.SUM,
            ),
        )


def test_builder_rejects_mixed_units(tmp_path: Path) -> None:
    with pytest.raises(FeatureBuildError, match="mixed units"):
        CanonicalObservationFeatureBuilder(_registry()).build(
            _observations(tmp_path, mixed_units=True),
            _metadata(),
            ObservationFeatureBuildSpec(
                feature_code="population_total",
                source_metric_code="population_count",
                aggregation=FeatureAggregation.SUM,
            ),
        )


def test_builder_rejects_catalog_lineage_mismatch(tmp_path: Path) -> None:
    metadata = _metadata().model_copy(update={"version": "different-version"})

    with pytest.raises(FeatureBuildError, match="does not match catalog metadata"):
        CanonicalObservationFeatureBuilder(_registry()).build(
            _observations(tmp_path),
            metadata,
            ObservationFeatureBuildSpec(
                feature_code="population_total",
                source_metric_code="population_count",
                aggregation=FeatureAggregation.SUM,
            ),
        )
