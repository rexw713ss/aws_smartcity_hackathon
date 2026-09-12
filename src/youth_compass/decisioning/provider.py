"""Provider boundary for retrieving materialized reusable feature values."""

from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from youth_compass.decisioning.contracts import CandidateFeatures, FeatureValue


class FeatureQuery(BaseModel):
    """Typed, allowlist-friendly request for latest feature values."""

    model_config = ConfigDict(frozen=True)

    feature_codes: tuple[str, ...] = Field(min_length=1)
    feature_versions: dict[str, str] = Field(default_factory=dict)
    entity_ids: tuple[str, ...] = ()
    as_of: AwareDatetime | None = None
    min_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    max_values: int = Field(default=10_000, ge=1, le=100_000)

    @field_validator("feature_codes", "entity_ids")
    @classmethod
    def identifiers_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("query identifiers must be unique")
        return value

    @model_validator(mode="after")
    def versions_must_only_reference_requested_features(self) -> "FeatureQuery":
        unknown = set(self.feature_versions) - set(self.feature_codes)
        if unknown:
            raise ValueError("feature_versions keys must be included in feature_codes")
        return self


class FeatureSet(BaseModel):
    """Provider result that can be passed directly into a decision scorer."""

    model_config = ConfigDict(frozen=True)

    values: tuple[FeatureValue, ...]
    truncated: bool = False

    @model_validator(mode="after")
    def entity_feature_pairs_must_be_unique(self) -> "FeatureSet":
        keys = [(value.entity_id, value.feature_code) for value in self.values]
        if len(keys) != len(set(keys)):
            raise ValueError("feature set entity-feature pairs must be unique")
        return self

    def as_candidates(self) -> tuple[CandidateFeatures, ...]:
        grouped: dict[str, dict[str, FeatureValue]] = {}
        for value in self.values:
            grouped.setdefault(value.entity_id, {})[value.feature_code] = value
        return tuple(
            CandidateFeatures(entity_id=entity_id, values=grouped[entity_id])
            for entity_id in sorted(grouped)
        )


@runtime_checkable
class FeatureProvider(Protocol):
    """Read latest versioned feature values without exposing storage-specific queries."""

    def get_features(self, query: FeatureQuery) -> FeatureSet:
        """Return the latest matching value for each entity-feature pair."""
        ...
