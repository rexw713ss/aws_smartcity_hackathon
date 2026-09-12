"""Semantic catalog contracts for agent-discoverable feature materializations."""

from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from youth_compass.decisioning.contracts import EntityType, FeatureDefinition


class FeatureMaterializationStatus(StrEnum):
    """Publication lifecycle for an immutable feature materialization."""

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class FeatureMaterializationMetadata(BaseModel):
    """Searchable coverage and lineage for one immutable feature snapshot."""

    model_config = ConfigDict(frozen=True)

    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    feature_version: str = Field(min_length=1)
    materialization_version: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    source_datasets: tuple[str, ...] = Field(min_length=1)
    entity_count: int = Field(ge=0)
    spatial_grain: str = Field(min_length=1)
    temporal_grain: str = Field(min_length=1)
    observed_from: AwareDatetime | None = None
    observed_to: AwareDatetime | None = None
    materialized_at: AwareDatetime
    fresh_until: AwareDatetime | None = None
    quality_score: float = Field(ge=0.0, le=1.0)
    supported_filters: tuple[str, ...] = ()
    status: FeatureMaterializationStatus

    @model_validator(mode="after")
    def coverage_and_lists_must_be_consistent(self) -> Self:
        if len(self.source_datasets) != len(set(self.source_datasets)):
            raise ValueError("source datasets must be unique")
        if len(self.supported_filters) != len(set(self.supported_filters)):
            raise ValueError("supported filters must be unique")
        if (
            self.observed_from is not None
            and self.observed_to is not None
            and self.observed_from > self.observed_to
        ):
            raise ValueError("observed_from must not exceed observed_to")
        if self.fresh_until is not None and self.fresh_until < self.materialized_at:
            raise ValueError("fresh_until must not precede materialized_at")
        return self


class FeatureSearchQuery(BaseModel):
    """Agent-safe semantic and coverage filters for feature discovery."""

    model_config = ConfigDict(frozen=True)

    text: str | None = None
    feature_codes: tuple[str, ...] = ()
    entity_type: EntityType | None = None
    spatial_grains: tuple[str, ...] = ()
    temporal_grains: tuple[str, ...] = ()
    required_filters: tuple[str, ...] = ()
    min_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    observed_at: AwareDatetime | None = None
    fresh_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def filters_must_be_unique(self) -> Self:
        for values in (
            self.feature_codes,
            self.spatial_grains,
            self.temporal_grains,
            self.required_filters,
        ):
            if len(values) != len(set(values)):
                raise ValueError("feature search filters must be unique")
        return self


class FeatureCatalogEntry(BaseModel):
    """A semantic definition paired with its current published materialization."""

    model_config = ConfigDict(frozen=True)

    definition: FeatureDefinition
    materialization: FeatureMaterializationMetadata


@runtime_checkable
class SemanticFeatureCatalog(Protocol):
    """Persist and discover versioned reusable features by meaning and coverage."""

    def register(self, materialization: FeatureMaterializationMetadata) -> None:
        """Register an immutable version and advance the pointer only when published."""
        ...

    def get(
        self, feature_code: str, materialization_version: str | None = None
    ) -> FeatureCatalogEntry:
        """Return an exact version or the current published version."""
        ...

    def search(self, query: FeatureSearchQuery) -> tuple[FeatureCatalogEntry, ...]:
        """Return current published features satisfying every requested constraint."""
        ...
