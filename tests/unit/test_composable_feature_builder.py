from datetime import UTC, datetime

import pytest

from youth_compass.decisioning import (
    ComposableFeatureBuilder,
    EntityType,
    FeatureCompositionError,
    FeatureDefinition,
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
    MinMaxFeatureBuildSpec,
    OptimizationDirection,
    RatioFeatureBuildSpec,
    ZeroDenominatorPolicy,
)

OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _registry() -> FeatureRegistry:
    return FeatureRegistry(
        (
            FeatureDefinition(
                feature_code="charger_count",
                display_name="Charger count",
                description="Existing public chargers.",
                entity_type=EntityType.LOCATION,
                unit_code="chargers",
                spatial_grain="district",
                temporal_grain="month",
                aggregation_method="sum",
                source_metric_codes=("charger_count",),
                valid_min=0,
            ),
            FeatureDefinition(
                feature_code="ev_demand",
                display_name="EV demand",
                description="Estimated EV charging demand.",
                entity_type=EntityType.LOCATION,
                unit_code="demand_index",
                spatial_grain="district",
                temporal_grain="month",
                aggregation_method="sum",
                source_metric_codes=("ev_demand",),
                valid_min=0,
            ),
            FeatureDefinition(
                feature_code="charger_competition",
                display_name="Charger competition",
                description="Charger supply relative to demand.",
                entity_type=EntityType.LOCATION,
                unit_code="chargers_per_demand_index",
                spatial_grain="district",
                temporal_grain="month",
                aggregation_method="ratio",
                source_feature_codes=("charger_count", "ev_demand"),
                valid_min=0,
            ),
            FeatureDefinition(
                feature_code="demand_score",
                display_name="Demand score",
                description="Normalized demand score.",
                entity_type=EntityType.LOCATION,
                unit_code="score_0_100",
                spatial_grain="district",
                temporal_grain="month",
                aggregation_method="min_max",
                source_feature_codes=("ev_demand",),
                valid_min=0,
                valid_max=100,
            ),
        )
    )


def _value(
    entity_id: str,
    feature_code: str,
    value: float,
    *,
    dataset_id: str | None = None,
) -> FeatureValue:
    source = dataset_id or feature_code
    return FeatureValue(
        entity_id=entity_id,
        feature_code=feature_code,
        value=value,
        observed_at=OBSERVED_AT,
        evidence=(
            FeatureEvidence(
                dataset_id=source,
                dataset_version="v1",
                source_uri=f"https://example.test/{source}",
                quality_score=0.9,
                retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ),
    )


def test_ratio_builder_aligns_entities_and_merges_evidence() -> None:
    result = ComposableFeatureBuilder(_registry()).build_ratio(
        (
            _value("district-a", "charger_count", 10),
            _value("district-a", "ev_demand", 100),
            _value("district-b", "charger_count", 5),
            _value("district-b", "ev_demand", 100),
        ),
        RatioFeatureBuildSpec(
            output_feature_code="charger_competition",
            numerator_feature_code="charger_count",
            denominator_feature_code="ev_demand",
        ),
    )

    assert [(value.entity_id, value.value) for value in result] == [
        ("district-a", 0.1),
        ("district-b", 0.05),
    ]
    assert {item.dataset_id for item in result[0].evidence} == {
        "charger_count",
        "ev_demand",
    }


def test_ratio_builder_has_explicit_zero_denominator_policy() -> None:
    inputs = (
        _value("district-a", "charger_count", 10),
        _value("district-a", "ev_demand", 0),
    )
    builder = ComposableFeatureBuilder(_registry())

    with pytest.raises(FeatureCompositionError, match="denominator is zero"):
        builder.build_ratio(
            inputs,
            RatioFeatureBuildSpec(
                output_feature_code="charger_competition",
                numerator_feature_code="charger_count",
                denominator_feature_code="ev_demand",
            ),
        )
    assert (
        builder.build_ratio(
            inputs,
            RatioFeatureBuildSpec(
                output_feature_code="charger_competition",
                numerator_feature_code="charger_count",
                denominator_feature_code="ev_demand",
                zero_denominator=ZeroDenominatorPolicy.SKIP,
            ),
        )
        == ()
    )


def test_min_max_builder_supports_both_directions() -> None:
    inputs = (
        _value("district-a", "ev_demand", 10),
        _value("district-b", "ev_demand", 30),
    )
    builder = ComposableFeatureBuilder(_registry())

    maximize = builder.build_min_max(
        inputs,
        MinMaxFeatureBuildSpec(
            output_feature_code="demand_score",
            input_feature_code="ev_demand",
        ),
    )
    minimize = builder.build_min_max(
        inputs,
        MinMaxFeatureBuildSpec(
            output_feature_code="demand_score",
            input_feature_code="ev_demand",
            direction=OptimizationDirection.MINIMIZE,
        ),
    )

    assert [value.value for value in maximize] == [0.0, 100.0]
    assert [value.value for value in minimize] == [100.0, 0.0]


def test_composition_rejects_undeclared_dependency() -> None:
    with pytest.raises(FeatureCompositionError, match="does not declare"):
        ComposableFeatureBuilder(_registry()).build_min_max(
            [_value("district-a", "charger_count", 10)],
            MinMaxFeatureBuildSpec(
                output_feature_code="demand_score",
                input_feature_code="charger_count",
            ),
        )


def test_composition_rejects_duplicate_entity_inputs() -> None:
    duplicate = _value("district-a", "ev_demand", 10)

    with pytest.raises(FeatureCompositionError, match="duplicate"):
        ComposableFeatureBuilder(_registry()).build_min_max(
            [duplicate, duplicate],
            MinMaxFeatureBuildSpec(
                output_feature_code="demand_score",
                input_feature_code="ev_demand",
            ),
        )
