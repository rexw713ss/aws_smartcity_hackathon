from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    CandidateFeatures,
    DecisionCriterion,
    DecisionProfile,
    DecisionProfileRegistry,
    DecisionScoringEngine,
    FeatureDefinition,
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
    OptimizationDirection,
)


def _evidence(dataset_id: str = "source_data") -> FeatureEvidence:
    return FeatureEvidence(
        dataset_id=dataset_id,
        dataset_version="v1",
        source_uri=f"https://example.test/{dataset_id}",
        quality_score=0.9,
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _value(entity_id: str, feature_code: str, value: float) -> FeatureValue:
    return FeatureValue(
        entity_id=entity_id,
        feature_code=feature_code,
        value=value,
        evidence=(_evidence(feature_code),),
    )


def _candidate(entity_id: str, **values: float) -> CandidateFeatures:
    return CandidateFeatures(
        entity_id=entity_id,
        values={code: _value(entity_id, code, value) for code, value in values.items()},
    )


def test_default_profiles_share_reusable_features() -> None:
    profiles = {profile.profile_code: profile for profile in DEFAULT_DECISION_PROFILES}
    home_codes = {criterion.feature_code for criterion in profiles["home_buying"].criteria}
    charger_codes = {
        criterion.feature_code for criterion in profiles["ev_charger_placement"].criteria
    }

    assert "transit_accessibility" in home_codes & charger_codes
    assert len(DEFAULT_FEATURES) == len({feature.feature_code for feature in DEFAULT_FEATURES})


def test_home_buying_profile_scores_and_explains_contributions() -> None:
    feature_registry = FeatureRegistry(DEFAULT_FEATURES)
    profile_registry = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES)
    result = DecisionScoringEngine(feature_registry).score(
        profile_registry.get("home_buying"),
        [
            _candidate(
                "location-a",
                property_cost=50,
                transit_accessibility=50,
                amenity_accessibility=80,
                environmental_risk=20,
            ),
            _candidate(
                "location-b",
                property_cost=100,
                transit_accessibility=100,
                amenity_accessibility=60,
                environmental_risk=40,
            ),
        ],
    )

    assert [candidate.entity_id for candidate in result.candidates] == [
        "location-a",
        "location-b",
    ]
    assert result.candidates[0].score == 75.0
    assert result.candidates[1].score == 25.0
    assert {item.feature_code for item in result.candidates[0].contributions} == {
        "property_cost",
        "transit_accessibility",
        "amenity_accessibility",
        "environmental_risk",
    }
    assert all(item.evidence for item in result.candidates[0].contributions)


def test_charger_constraint_excludes_infeasible_site() -> None:
    engine = DecisionScoringEngine(FeatureRegistry(DEFAULT_FEATURES))
    profile = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES).get("ev_charger_placement")
    result = engine.score(
        profile,
        [
            _candidate(
                "site-a",
                ev_demand_proxy=80,
                parking_availability=70,
                grid_accessibility=80,
                charger_competition=20,
                site_feasibility=1,
            ),
            _candidate(
                "site-b",
                ev_demand_proxy=100,
                parking_availability=100,
                grid_accessibility=100,
                charger_competition=0,
                site_feasibility=0,
            ),
        ],
    )

    assert result.candidates[0].entity_id == "site-a"
    assert result.candidates[0].eligible is True
    assert result.candidates[1].entity_id == "site-b"
    assert result.candidates[1].eligible is False
    assert result.candidates[1].score is None
    assert "site_feasibility" in result.candidates[1].failed_constraints[0]


def test_missing_optional_feature_renormalizes_present_weights() -> None:
    registry = FeatureRegistry(DEFAULT_FEATURES)
    profile = DecisionProfile(
        profile_code="small_model",
        version="v1",
        display_name="Small model",
        candidate_type="location",
        criteria=(
            DecisionCriterion(
                feature_code="amenity_accessibility",
                weight=0.8,
                direction=OptimizationDirection.MAXIMIZE,
            ),
            DecisionCriterion(
                feature_code="transit_accessibility",
                weight=0.2,
                direction=OptimizationDirection.MAXIMIZE,
                required=False,
            ),
        ),
    )
    result = DecisionScoringEngine(registry).score(
        profile,
        [_candidate("location-a", amenity_accessibility=50)],
    )

    assert result.candidates[0].score == 100.0
    assert result.candidates[0].contributions[0].effective_weight == 1.0


def test_missing_required_feature_makes_candidate_ineligible() -> None:
    profile = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES).get("home_buying")
    result = DecisionScoringEngine(FeatureRegistry(DEFAULT_FEATURES)).score(
        profile,
        [_candidate("location-a", property_cost=50)],
    )

    assert result.candidates[0].eligible is False
    assert set(result.candidates[0].missing_required_features) == {
        "transit_accessibility",
        "amenity_accessibility",
        "environmental_risk",
    }


def test_profile_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match=r"weights must sum to 1\.0"):
        DecisionProfile(
            profile_code="invalid",
            version="v1",
            display_name="Invalid",
            candidate_type="location",
            criteria=(
                DecisionCriterion(
                    feature_code="property_cost",
                    weight=0.5,
                    direction=OptimizationDirection.MINIMIZE,
                ),
            ),
        )


def test_registry_rejects_conflicting_feature_contract() -> None:
    registry = FeatureRegistry(DEFAULT_FEATURES)
    original = registry.get("property_cost")
    conflicting = FeatureDefinition.model_validate(
        {**original.model_dump(), "unit_code": "usd_per_sqm"}
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(conflicting)


def test_scoring_rejects_feature_value_outside_contract_bounds() -> None:
    profile = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES).get("home_buying")
    engine = DecisionScoringEngine(FeatureRegistry(DEFAULT_FEATURES))

    with pytest.raises(ValueError, match="exceeds its valid maximum"):
        engine.score(
            profile,
            [
                _candidate(
                    "location-a",
                    property_cost=50,
                    transit_accessibility=101,
                    amenity_accessibility=80,
                    environmental_risk=20,
                )
            ],
        )


def test_scoring_requires_at_least_one_candidate() -> None:
    profile = DecisionProfileRegistry(DEFAULT_DECISION_PROFILES).get("home_buying")

    with pytest.raises(ValueError, match="at least one candidate"):
        DecisionScoringEngine(FeatureRegistry(DEFAULT_FEATURES)).score(profile, [])
