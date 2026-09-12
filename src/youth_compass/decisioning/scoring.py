"""Deterministic scoring over reusable feature values."""

from collections.abc import Callable, Iterable

from youth_compass.decisioning.contracts import (
    CandidateFeatures,
    CandidateScore,
    ConstraintOperator,
    DecisionProfile,
    DecisionResult,
    FeatureContribution,
    FeatureDefinition,
    OptimizationDirection,
)
from youth_compass.decisioning.registry import FeatureRegistry

_COMPARATORS: dict[ConstraintOperator, Callable[[float, float], bool]] = {
    ConstraintOperator.GREATER_THAN: lambda value, threshold: value > threshold,
    ConstraintOperator.GREATER_THAN_OR_EQUAL: lambda value, threshold: value >= threshold,
    ConstraintOperator.LESS_THAN: lambda value, threshold: value < threshold,
    ConstraintOperator.LESS_THAN_OR_EQUAL: lambda value, threshold: value <= threshold,
    ConstraintOperator.EQUAL: lambda value, threshold: value == threshold,
}


class DecisionScoringEngine:
    """Validate, normalize, constrain, and rank candidates without an LLM."""

    def __init__(self, features: FeatureRegistry) -> None:
        self._features = features

    def score(
        self,
        profile: DecisionProfile,
        candidates: Iterable[CandidateFeatures],
    ) -> DecisionResult:
        candidate_list = list(candidates)
        self._validate_profile(profile)
        if not candidate_list:
            raise ValueError("at least one candidate is required")
        if len({candidate.entity_id for candidate in candidate_list}) != len(candidate_list):
            raise ValueError("candidate entity_id values must be unique")

        preliminary = [self._eligibility(profile, candidate) for candidate in candidate_list]
        eligible_ids = {
            candidate.entity_id
            for candidate, failed, missing in preliminary
            if not failed and not missing
        }
        ranges = self._feature_ranges(profile, candidate_list, eligible_ids)

        results: list[CandidateScore] = []
        for candidate, failed, missing in preliminary:
            if failed or missing:
                results.append(
                    CandidateScore(
                        entity_id=candidate.entity_id,
                        entity_name=candidate.entity_name,
                        eligible=False,
                        failed_constraints=tuple(failed),
                        missing_required_features=tuple(missing),
                    )
                )
                continue
            results.append(self._score_candidate(profile, candidate, ranges))

        results.sort(
            key=lambda result: (
                not result.eligible,
                -(result.score if result.score is not None else -1.0),
                result.entity_id,
            )
        )
        return DecisionResult(
            profile_code=profile.profile_code,
            profile_version=profile.version,
            candidates=tuple(results),
        )

    def _validate_profile(self, profile: DecisionProfile) -> None:
        codes = {
            *(criterion.feature_code for criterion in profile.criteria),
            *(constraint.feature_code for constraint in profile.constraints),
        }
        for code in codes:
            self._features.get(code)

    def _eligibility(
        self,
        profile: DecisionProfile,
        candidate: CandidateFeatures,
    ) -> tuple[CandidateFeatures, list[str], list[str]]:
        failed: list[str] = []
        missing = [
            criterion.feature_code
            for criterion in profile.criteria
            if criterion.required and criterion.feature_code not in candidate.values
        ]
        for constraint in profile.constraints:
            feature = candidate.values.get(constraint.feature_code)
            if feature is None:
                failed.append(f"{constraint.feature_code}: missing ({constraint.reason})")
                continue
            self._validate_value(self._features.get(constraint.feature_code), feature.value)
            comparator = _COMPARATORS[constraint.operator]
            if not comparator(feature.value, constraint.threshold):
                failed.append(
                    f"{constraint.feature_code} {constraint.operator.value} "
                    f"{constraint.threshold:g}: {constraint.reason}"
                )
        return candidate, failed, missing

    def _feature_ranges(
        self,
        profile: DecisionProfile,
        candidates: list[CandidateFeatures],
        eligible_ids: set[str],
    ) -> dict[str, tuple[float, float]]:
        ranges: dict[str, tuple[float, float]] = {}
        for criterion in profile.criteria:
            values = [
                candidate.values[criterion.feature_code].value
                for candidate in candidates
                if candidate.entity_id in eligible_ids
                and criterion.feature_code in candidate.values
            ]
            if values:
                ranges[criterion.feature_code] = (min(values), max(values))
        return ranges

    def _score_candidate(
        self,
        profile: DecisionProfile,
        candidate: CandidateFeatures,
        ranges: dict[str, tuple[float, float]],
    ) -> CandidateScore:
        present = [
            criterion
            for criterion in profile.criteria
            if criterion.feature_code in candidate.values
        ]
        present_weight = sum(criterion.weight for criterion in present)
        contributions: list[FeatureContribution] = []
        score = 0.0
        for criterion in present:
            feature = candidate.values[criterion.feature_code]
            definition = self._features.get(criterion.feature_code, feature.feature_version)
            self._validate_value(definition, feature.value)
            lower, upper = ranges[criterion.feature_code]
            normalized = _normalize(feature.value, lower, upper, criterion.direction)
            effective_weight = criterion.weight / present_weight
            points = normalized * effective_weight * 100.0
            score += points
            contributions.append(
                FeatureContribution(
                    feature_code=criterion.feature_code,
                    feature_name=definition.display_name,
                    feature_version=feature.feature_version,
                    raw_value=feature.value,
                    normalized_value=round(normalized, 6),
                    effective_weight=round(effective_weight, 6),
                    points=round(points, 4),
                    evidence=feature.evidence,
                )
            )
        return CandidateScore(
            entity_id=candidate.entity_id,
            entity_name=candidate.entity_name,
            eligible=True,
            score=round(score, 4),
            contributions=tuple(contributions),
        )

    @staticmethod
    def _validate_value(definition: FeatureDefinition, value: float) -> None:
        if definition.valid_min is not None and value < definition.valid_min:
            raise ValueError(f"{definition.feature_code} is below its valid minimum")
        if definition.valid_max is not None and value > definition.valid_max:
            raise ValueError(f"{definition.feature_code} exceeds its valid maximum")


def _normalize(
    value: float,
    lower: float,
    upper: float,
    direction: OptimizationDirection,
) -> float:
    if lower == upper:
        return 1.0
    normalized = (value - lower) / (upper - lower)
    return 1.0 - normalized if direction is OptimizationDirection.MINIMIZE else normalized
