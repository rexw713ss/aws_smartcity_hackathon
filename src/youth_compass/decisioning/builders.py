"""Contracts and pure builders for deriving reusable features."""

import math
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from youth_compass.decisioning.contracts import (
    FeatureEvidence,
    FeatureValue,
    OptimizationDirection,
)
from youth_compass.decisioning.registry import FeatureRegistry


class FeatureAggregation(StrEnum):
    """Allowlisted aggregation functions for observation feature builders."""

    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MINIMUM = "min"
    MAXIMUM = "max"


class ObservationFeatureBuildSpec(BaseModel):
    """Typed recipe for one district feature derived from canonical observations."""

    model_config = ConfigDict(frozen=True)

    feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_metric_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    aggregation: FeatureAggregation
    year_gregorian: int | None = Field(default=None, ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def month_requires_year(self) -> "ObservationFeatureBuildSpec":
        if self.month is not None and self.year_gregorian is None:
            raise ValueError("month requires year_gregorian")
        return self


class ZeroDenominatorPolicy(StrEnum):
    """Explicit handling for ratios whose denominator is zero."""

    ERROR = "error"
    SKIP = "skip"


class RatioFeatureBuildSpec(BaseModel):
    """Recipe for an entity-aligned ratio of two reusable features."""

    model_config = ConfigDict(frozen=True)

    output_feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    numerator_feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    denominator_feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    scale: float = 1.0
    zero_denominator: ZeroDenominatorPolicy = ZeroDenominatorPolicy.ERROR
    require_same_observation_time: bool = True

    @field_validator("scale")
    @classmethod
    def scale_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("ratio scale must be finite")
        return value


class MinMaxFeatureBuildSpec(BaseModel):
    """Recipe for scaling one feature across entities to a bounded score."""

    model_config = ConfigDict(frozen=True)

    output_feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    input_feature_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    direction: OptimizationDirection = OptimizationDirection.MAXIMIZE
    output_min: float = 0.0
    output_max: float = 100.0

    @model_validator(mode="after")
    def output_bounds_must_be_finite_and_ordered(self) -> "MinMaxFeatureBuildSpec":
        if not math.isfinite(self.output_min) or not math.isfinite(self.output_max):
            raise ValueError("normalization bounds must be finite")
        if self.output_min >= self.output_max:
            raise ValueError("output_min must be less than output_max")
        return self


class FeatureCompositionError(ValueError):
    """Reusable feature inputs cannot satisfy a composition recipe."""


class ComposableFeatureBuilder:
    """Build ratios and normalized scores while preserving all source evidence."""

    def __init__(self, registry: FeatureRegistry) -> None:
        self._registry = registry

    def build_ratio(
        self,
        values: Iterable[FeatureValue],
        spec: RatioFeatureBuildSpec,
    ) -> tuple[FeatureValue, ...]:
        output = self._registry.get(spec.output_feature_code)
        required_sources = {spec.numerator_feature_code, spec.denominator_feature_code}
        if not required_sources.issubset(output.source_feature_codes):
            raise FeatureCompositionError(
                f"feature {output.feature_code!r} does not declare the requested source features"
            )
        records = list(values)
        numerator = self._index(records, spec.numerator_feature_code)
        denominator = self._index(records, spec.denominator_feature_code)
        results: list[FeatureValue] = []
        for entity_id in sorted(set(numerator) & set(denominator)):
            top = numerator[entity_id]
            bottom = denominator[entity_id]
            if spec.require_same_observation_time and top.observed_at != bottom.observed_at:
                raise FeatureCompositionError(
                    f"ratio inputs for entity {entity_id!r} have different observation times"
                )
            if bottom.value == 0:
                if spec.zero_denominator is ZeroDenominatorPolicy.SKIP:
                    continue
                raise FeatureCompositionError(f"ratio denominator is zero for entity {entity_id!r}")
            result = top.value / bottom.value * spec.scale
            _validate_output_value(output.feature_code, output.valid_min, output.valid_max, result)
            results.append(
                FeatureValue(
                    entity_id=entity_id,
                    feature_code=output.feature_code,
                    feature_version=output.version,
                    value=result,
                    observed_at=_latest_observation_time(top, bottom),
                    evidence=_merge_evidence(top.evidence, bottom.evidence),
                )
            )
        return tuple(results)

    def build_min_max(
        self,
        values: Iterable[FeatureValue],
        spec: MinMaxFeatureBuildSpec,
    ) -> tuple[FeatureValue, ...]:
        output = self._registry.get(spec.output_feature_code)
        if spec.input_feature_code not in output.source_feature_codes:
            raise FeatureCompositionError(
                f"feature {output.feature_code!r} does not declare source feature "
                f"{spec.input_feature_code!r}"
            )
        indexed = self._index(list(values), spec.input_feature_code)
        if not indexed:
            raise FeatureCompositionError(
                f"no values found for source feature {spec.input_feature_code!r}"
            )
        lower = min(value.value for value in indexed.values())
        upper = max(value.value for value in indexed.values())
        width = spec.output_max - spec.output_min
        results: list[FeatureValue] = []
        for entity_id, source in sorted(indexed.items()):
            normalized = 1.0 if lower == upper else (source.value - lower) / (upper - lower)
            if spec.direction is OptimizationDirection.MINIMIZE:
                normalized = 1.0 - normalized
            result = spec.output_min + normalized * width
            _validate_output_value(output.feature_code, output.valid_min, output.valid_max, result)
            results.append(
                FeatureValue(
                    entity_id=entity_id,
                    feature_code=output.feature_code,
                    feature_version=output.version,
                    value=result,
                    observed_at=source.observed_at,
                    evidence=source.evidence,
                )
            )
        return tuple(results)

    def _index(
        self,
        values: list[FeatureValue],
        feature_code: str,
    ) -> dict[str, FeatureValue]:
        records: dict[str, FeatureValue] = {}
        for value in values:
            if value.feature_code != feature_code:
                continue
            self._registry.get(value.feature_code, value.feature_version)
            if value.entity_id in records:
                raise FeatureCompositionError(
                    f"duplicate {feature_code!r} value for entity {value.entity_id!r}"
                )
            records[value.entity_id] = value
        return records


def _merge_evidence(
    first: tuple[FeatureEvidence, ...],
    second: tuple[FeatureEvidence, ...],
) -> tuple[FeatureEvidence, ...]:
    merged: dict[tuple[str, str, str], FeatureEvidence] = {}
    for item in (*first, *second):
        merged[(item.dataset_id, item.dataset_version, item.source_uri)] = item
    return tuple(merged[key] for key in sorted(merged))


def _latest_observation_time(
    first: FeatureValue,
    second: FeatureValue,
) -> datetime | None:
    times = [value for value in (first.observed_at, second.observed_at) if value is not None]
    return max(times) if times else None


def _validate_output_value(
    feature_code: str,
    valid_min: float | None,
    valid_max: float | None,
    value: float,
) -> None:
    if not math.isfinite(value):
        raise FeatureCompositionError(f"feature {feature_code!r} produced a non-finite value")
    if valid_min is not None and value < valid_min:
        raise FeatureCompositionError(f"feature {feature_code!r} is below its valid minimum")
    if valid_max is not None and value > valid_max:
        raise FeatureCompositionError(f"feature {feature_code!r} exceeds its valid maximum")
