"""Portable contracts for reusable features and decision-specific scoring."""

import math
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class EntityType(StrEnum):
    """Canonical subjects for which a feature can be calculated."""

    LOCATION = "location"
    PROPERTY = "property"
    DISTRICT = "district"


class OptimizationDirection(StrEnum):
    """Whether a larger or smaller feature value is preferred."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class ConstraintOperator(StrEnum):
    """Allowlisted comparison operators for hard decision constraints."""

    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"


class FeatureDefinition(BaseModel):
    """Semantic contract for one reusable, independently materializable feature."""

    model_config = ConfigDict(frozen=True)

    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(default="v1", min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    entity_type: EntityType
    unit_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    spatial_grain: str = Field(min_length=1)
    temporal_grain: str = Field(min_length=1)
    aggregation_method: str = Field(min_length=1)
    source_metric_codes: tuple[str, ...] = ()
    source_feature_codes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    valid_min: float | None = None
    valid_max: float | None = None

    @model_validator(mode="after")
    def bounds_must_be_ordered(self) -> Self:
        if not self.source_metric_codes and not self.source_feature_codes:
            raise ValueError("a feature must declare at least one source metric or feature")
        if len(self.source_metric_codes) != len(set(self.source_metric_codes)):
            raise ValueError("source metric codes must be unique")
        if len(self.source_feature_codes) != len(set(self.source_feature_codes)):
            raise ValueError("source feature codes must be unique")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("feature tags must be unique")
        if (
            self.valid_min is not None
            and self.valid_max is not None
            and self.valid_min > self.valid_max
        ):
            raise ValueError("valid_min must not exceed valid_max")
        return self


class FeatureEvidence(BaseModel):
    """Dataset-version evidence carried with every calculated feature value."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    dataset_version: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    quality_score: float = Field(ge=0.0, le=1.0)
    retrieved_at: AwareDatetime


class FeatureValue(BaseModel):
    """A feature value at a canonical entity with reproducible evidence."""

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(min_length=1)
    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    feature_version: str = Field(default="v1", min_length=1)
    value: float
    observed_at: AwareDatetime | None = None
    evidence: tuple[FeatureEvidence, ...] = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("feature value must be finite")
        return value


class DecisionCriterion(BaseModel):
    """A weighted reusable feature in a particular decision model."""

    model_config = ConfigDict(frozen=True)

    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    weight: float = Field(gt=0.0, le=1.0)
    direction: OptimizationDirection
    required: bool = True


class DecisionConstraint(BaseModel):
    """A deterministic feasibility rule evaluated before ranking."""

    model_config = ConfigDict(frozen=True)

    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operator: ConstraintOperator
    threshold: float
    reason: str = Field(min_length=1)

    @field_validator("threshold")
    @classmethod
    def threshold_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("constraint threshold must be finite")
        return value


class DecisionProfile(BaseModel):
    """Versioned policy describing how reusable features support one decision."""

    model_config = ConfigDict(frozen=True)

    profile_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    candidate_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    criteria: tuple[DecisionCriterion, ...] = Field(min_length=1)
    constraints: tuple[DecisionConstraint, ...] = ()

    @model_validator(mode="after")
    def criteria_must_be_unique_and_normalized(self) -> Self:
        codes = [criterion.feature_code for criterion in self.criteria]
        if len(codes) != len(set(codes)):
            raise ValueError("decision criteria feature codes must be unique")
        if not math.isclose(sum(item.weight for item in self.criteria), 1.0, abs_tol=1e-9):
            raise ValueError("decision criterion weights must sum to 1.0")
        return self


class CandidateFeatures(BaseModel):
    """All currently available reusable features for one decision candidate."""

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(min_length=1)
    entity_name: str | None = None
    values: dict[str, FeatureValue]

    @model_validator(mode="after")
    def feature_keys_and_entities_must_match(self) -> Self:
        for feature_code, feature in self.values.items():
            if feature_code != feature.feature_code:
                raise ValueError("feature value key must match feature_code")
            if feature.entity_id != self.entity_id:
                raise ValueError("feature values must belong to the candidate entity")
        return self


class FeatureContribution(BaseModel):
    """An auditable component of a candidate's final score."""

    feature_code: str
    feature_name: str | None = None
    feature_version: str
    raw_value: float
    normalized_value: float = Field(ge=0.0, le=1.0)
    effective_weight: float = Field(gt=0.0, le=1.0)
    points: float = Field(ge=0.0, le=100.0)
    evidence: tuple[FeatureEvidence, ...]


class CandidateScore(BaseModel):
    """Feasibility and ranking result for one candidate."""

    entity_id: str
    entity_name: str | None = None
    eligible: bool
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    contributions: tuple[FeatureContribution, ...] = ()
    failed_constraints: tuple[str, ...] = ()
    missing_required_features: tuple[str, ...] = ()


class DecisionResult(BaseModel):
    """A deterministic, versioned ranking suitable for an agent to explain."""

    profile_code: str
    profile_version: str
    candidates: tuple[CandidateScore, ...]
