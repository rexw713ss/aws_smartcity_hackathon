"""Typed multi-dataset analysis plans and deterministic safe-join validation."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JoinCardinality(StrEnum):
    """Declared relationship between left and right inputs at their current grain."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class JoinType(StrEnum):
    """Allowlisted relational join behavior."""

    INNER = "inner"
    LEFT = "left"


class AnalysisInput(BaseModel):
    """One immutable published dataset participating in an analysis."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    dataset_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    dataset_version: str = Field(min_length=1)
    dimensions: tuple[str, ...] = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    grain: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fields_and_grain_must_be_unique_and_consistent(self) -> Self:
        for values in (self.dimensions, self.metrics, self.grain):
            if len(values) != len(set(values)):
                raise ValueError("analysis input fields must be unique")
        if not set(self.grain).issubset(self.dimensions):
            raise ValueError("analysis input grain must be contained in dimensions")
        if set(self.dimensions) & set(self.metrics):
            raise ValueError("analysis dimensions and metrics must not overlap")
        return self


class PreAggregation(BaseModel):
    """Required grain reduction performed before a join."""

    model_config = ConfigDict(frozen=True)

    input_alias: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    group_by: tuple[str, ...] = Field(min_length=1)
    metric_aggregations: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def fields_must_be_unique(self) -> Self:
        if len(self.group_by) != len(set(self.group_by)):
            raise ValueError("pre-aggregation group_by fields must be unique")
        return self


class AnalysisJoin(BaseModel):
    """A declared join whose compatibility can be checked without rendering SQL."""

    model_config = ConfigDict(frozen=True)

    left_alias: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    right_alias: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    keys: tuple[str, ...] = Field(min_length=1)
    join_type: JoinType = JoinType.INNER
    cardinality: JoinCardinality

    @model_validator(mode="after")
    def aliases_and_keys_must_be_valid(self) -> Self:
        if self.left_alias == self.right_alias:
            raise ValueError("a dataset cannot be joined to itself under the same alias")
        if len(self.keys) != len(set(self.keys)):
            raise ValueError("join keys must be unique")
        return self


class AnalysisPlan(BaseModel):
    """Agent-produced declarative plan accepted only after deterministic validation."""

    model_config = ConfigDict(frozen=True)

    inputs: tuple[AnalysisInput, ...] = Field(min_length=1)
    pre_aggregations: tuple[PreAggregation, ...] = ()
    joins: tuple[AnalysisJoin, ...] = ()
    output_dimensions: tuple[str, ...] = Field(min_length=1)
    output_metrics: tuple[str, ...] = Field(min_length=1)
    max_rows: int = Field(default=10_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def aliases_and_outputs_must_be_unique(self) -> Self:
        aliases = [item.alias for item in self.inputs]
        if len(aliases) != len(set(aliases)):
            raise ValueError("analysis input aliases must be unique")
        for values in (self.output_dimensions, self.output_metrics):
            if len(values) != len(set(values)):
                raise ValueError("analysis output fields must be unique")
        if set(self.output_dimensions) & set(self.output_metrics):
            raise ValueError("analysis output dimensions and metrics must not overlap")
        return self


class PlanValidationIssue(BaseModel):
    """Stable machine-readable reason an analysis plan is unsafe or invalid."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str
    blocking: bool = True


class PlanValidationReport(BaseModel):
    """Deterministic validation result consumed before query rendering."""

    valid: bool
    issues: tuple[PlanValidationIssue, ...] = ()


class AnalysisPlanValidator:
    """Fail closed on unknown fields, disconnected joins, and unsafe cardinality."""

    _AGGREGATIONS = frozenset({"sum", "mean", "median", "min", "max", "count"})

    def validate(self, plan: AnalysisPlan) -> PlanValidationReport:
        issues: list[PlanValidationIssue] = []
        inputs = {item.alias: item for item in plan.inputs}
        aggregations: dict[str, PreAggregation] = {}
        for aggregation in plan.pre_aggregations:
            source = inputs.get(aggregation.input_alias)
            if source is None:
                issues.append(
                    _issue(
                        "UNKNOWN_AGGREGATION_INPUT", f"unknown input {aggregation.input_alias!r}"
                    )
                )
                continue
            if aggregation.input_alias in aggregations:
                issues.append(
                    _issue(
                        "DUPLICATE_PRE_AGGREGATION",
                        f"input {aggregation.input_alias!r} has multiple pre-aggregations",
                    )
                )
            aggregations[aggregation.input_alias] = aggregation
            unknown_groups = set(aggregation.group_by) - set(source.dimensions)
            unknown_metrics = set(aggregation.metric_aggregations) - set(source.metrics)
            bad_functions = set(aggregation.metric_aggregations.values()) - self._AGGREGATIONS
            if unknown_groups:
                issues.append(
                    _issue("UNKNOWN_GROUP_FIELD", f"unknown group fields: {sorted(unknown_groups)}")
                )
            if unknown_metrics:
                issues.append(
                    _issue(
                        "UNKNOWN_AGGREGATE_METRIC", f"unknown metrics: {sorted(unknown_metrics)}"
                    )
                )
            if bad_functions:
                issues.append(
                    _issue(
                        "UNSAFE_AGGREGATION",
                        f"aggregation functions not allowed: {sorted(bad_functions)}",
                    )
                )

        joined = {plan.inputs[0].alias}
        for join in plan.joins:
            left = inputs.get(join.left_alias)
            right = inputs.get(join.right_alias)
            if left is None or right is None:
                issues.append(
                    _issue("UNKNOWN_JOIN_INPUT", "join references an unknown input alias")
                )
                continue
            if join.left_alias not in joined:
                issues.append(
                    _issue("DISCONNECTED_JOIN", f"left input {join.left_alias!r} is not joined yet")
                )
            joined.add(join.right_alias)
            left_grain = _effective_grain(left, aggregations.get(left.alias))
            right_grain = _effective_grain(right, aggregations.get(right.alias))
            for source, grain in ((left, left_grain), (right, right_grain)):
                missing = set(join.keys) - set(grain)
                if missing:
                    issues.append(
                        _issue(
                            "JOIN_KEY_OUTSIDE_GRAIN",
                            f"join keys {sorted(missing)} are outside {source.alias!r} grain",
                        )
                    )
            expected = _cardinality(join.keys, left_grain, right_grain)
            if expected is JoinCardinality.MANY_TO_MANY:
                issues.append(
                    _issue(
                        "UNSAFE_MANY_TO_MANY",
                        "effective grains produce a many-to-many join; aggregate to join keys",
                    )
                )
            elif join.cardinality is not expected:
                issues.append(
                    _issue(
                        "CARDINALITY_MISMATCH",
                        f"declared {join.cardinality.value}, expected {expected.value}",
                    )
                )

        if len(inputs) > 1 and joined != set(inputs):
            issues.append(
                _issue("UNJOINED_INPUT", f"unjoined inputs: {sorted(set(inputs) - joined)}")
            )
        available_dimensions = set().union(*(set(item.dimensions) for item in plan.inputs))
        available_metrics = set().union(*(set(item.metrics) for item in plan.inputs))
        if unknown := set(plan.output_dimensions) - available_dimensions:
            issues.append(
                _issue("UNKNOWN_OUTPUT_DIMENSION", f"unknown dimensions: {sorted(unknown)}")
            )
        if unknown := set(plan.output_metrics) - available_metrics:
            issues.append(_issue("UNKNOWN_OUTPUT_METRIC", f"unknown metrics: {sorted(unknown)}"))
        return PlanValidationReport(valid=not issues, issues=tuple(issues))


def _effective_grain(
    source: AnalysisInput,
    aggregation: PreAggregation | None,
) -> tuple[str, ...]:
    return aggregation.group_by if aggregation is not None else source.grain


def _cardinality(
    keys: tuple[str, ...],
    left_grain: tuple[str, ...],
    right_grain: tuple[str, ...],
) -> JoinCardinality:
    key_set = set(keys)
    left_unique = key_set == set(left_grain)
    right_unique = key_set == set(right_grain)
    if left_unique and right_unique:
        return JoinCardinality.ONE_TO_ONE
    if left_unique:
        return JoinCardinality.ONE_TO_MANY
    if right_unique:
        return JoinCardinality.MANY_TO_ONE
    return JoinCardinality.MANY_TO_MANY


def _issue(code: str, message: str) -> PlanValidationIssue:
    return PlanValidationIssue(code=code, message=message)
