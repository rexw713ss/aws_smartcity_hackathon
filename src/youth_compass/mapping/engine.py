"""Deterministic schema mapping proposal and validation engine."""

import re
from dataclasses import dataclass

from youth_compass.domain.contracts import (
    ColumnMapping,
    DatasetGrain,
    DatasetRole,
    MappingAnalysis,
    MappingProposal,
    MappingValidationIssue,
    MappingValidationReport,
    MetricMapping,
    PopulationScope,
)
from youth_compass.domain.profiles import ColumnProfile, DatasetProfile
from youth_compass.domain.types import PrimitiveType, SemanticRole, WarningSeverity
from youth_compass.mapping.registry import (
    CanonicalFieldRule,
    find_field_rule,
    normalize_header,
)
from youth_compass.mapping.transform_registry import get_transformation


class MappingProposalError(ValueError):
    """Raised when a profile cannot form the minimum mapping contract."""


@dataclass(frozen=True, slots=True)
class MappingOptions:
    topic_hint: str | None = None
    require_human_approval: bool = True
    review_confidence_threshold: float = 0.95

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_confidence_threshold <= 1.0:
            raise ValueError("review_confidence_threshold must be between 0 and 1")


_TOPIC_METRIC_CODES = {
    "population": "population_count",
    "education": "education_population",
    "marriage": "marital_population",
    "migration": "migration_count",
    "household_registration": "registration_count",
    "marriage_events": "marriage_event_count",
}

_KNOWN_METRICS: dict[str, tuple[str, str | None, str]] = {
    "jobseekers": ("job_seekers", "persons", "sum"),
    "人數": ("person_count", "persons", "sum"),
    "人口": ("population_count", "persons", "sum"),
    "count": ("count", "persons", "sum"),
    "population": ("population_count", "persons", "sum"),
    "納稅單位": ("tax_units", "households", "sum"),
    "納稅單位戶": ("tax_units", "households", "sum"),
    "平均數": ("average_income", None, "mean"),
    "中位數": ("median_income", None, "median"),
    "綜合所得總額": ("total_income", None, "sum"),
}


def analyze_mapping(
    profile: DatasetProfile,
    options: MappingOptions | None = None,
) -> MappingAnalysis:
    options = options or MappingOptions()
    proposal = propose_mapping(profile, options)
    validation = validate_mapping(profile, proposal, options)
    return MappingAnalysis(profile=profile, proposal=proposal, validation=validation)


def propose_mapping(
    profile: DatasetProfile,
    options: MappingOptions | None = None,
) -> MappingProposal:
    options = options or MappingOptions()
    topic = options.topic_hint or _infer_topic(profile)
    has_age_dimension = any(
        column.non_null_count > 0
        and column.semantic_role
        in {SemanticRole.AGE_LABEL, SemanticRole.AGE_LOWER, SemanticRole.AGE_UPPER}
        for column in profile.columns
    )
    population_scope = (
        PopulationScope.YOUTH_SPECIFIC if has_age_dimension else PopulationScope.DISTRICT_CONTEXT
    )
    dataset_role = DatasetRole.FACT if has_age_dimension else DatasetRole.CONTEXT

    columns: list[ColumnMapping] = []
    metrics: list[MetricMapping] = []
    warnings: list[str] = []
    grain_candidates: list[tuple[str, CanonicalFieldRule]] = []

    for column in profile.columns:
        rule = find_field_rule(column.name)
        if rule is not None:
            mapping = _map_canonical_column(column, rule, profile)
            columns.append(mapping)
            if rule.grain_dimension and column.non_null_count > 0:
                grain_candidates.append((mapping.target_field, rule))
            continue
        if column.semantic_role == SemanticRole.METRIC:
            metrics.append(_map_metric(column, topic, population_scope))
            continue
        warnings.append(f"Unmapped column {column.name!r} requires review")

    grain_dimensions = _select_grain_dimensions(grain_candidates)
    if not grain_dimensions:
        raise MappingProposalError("No canonical grain dimensions could be inferred")

    confidence_values = [mapping.confidence for mapping in columns] + [
        metric.confidence for metric in metrics
    ]
    overall_confidence = (
        sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    )
    if not has_age_dimension:
        warnings.append(
            "No populated age dimension was detected; metrics are district context, "
            "not youth-specific"
        )
    if topic == "unknown":
        warnings.append("Dataset topic could not be inferred deterministically")
    if profile.geography_coverage.unknown_values:
        warnings.append(
            f"Unknown district values: {', '.join(profile.geography_coverage.unknown_values)}"
        )

    requires_approval = (
        options.require_human_approval
        or overall_confidence < options.review_confidence_threshold
        or bool(warnings)
        or any(metric.unit_code is None for metric in metrics)
    )
    return MappingProposal(
        topic=topic,
        dataset_role=dataset_role,
        grain=DatasetGrain(dimensions=grain_dimensions),
        columns=columns,
        metrics=metrics,
        overall_confidence=round(overall_confidence, 4),
        warnings=warnings,
        requires_human_approval=requires_approval,
    )


def validate_mapping(
    profile: DatasetProfile,
    proposal: MappingProposal,
    options: MappingOptions | None = None,
) -> MappingValidationReport:
    options = options or MappingOptions()
    issues: list[MappingValidationIssue] = []
    profile_columns = {column.name: column for column in profile.columns}

    source_columns = [mapping.source_column for mapping in proposal.columns]
    if len(source_columns) != len(set(source_columns)):
        issues.append(
            _validation_issue(
                "DUPLICATE_SOURCE_MAPPING",
                "A source column was mapped more than once",
                blocking=True,
            )
        )
    target_fields = [mapping.target_field for mapping in proposal.columns]
    if len(target_fields) != len(set(target_fields)):
        issues.append(
            _validation_issue(
                "DUPLICATE_TARGET_MAPPING",
                "Multiple source columns map to the same canonical field",
                blocking=True,
            )
        )
    mapped_targets = set(target_fields)
    for dimension in proposal.grain.dimensions:
        if dimension not in mapped_targets:
            issues.append(
                _validation_issue(
                    "UNKNOWN_GRAIN_DIMENSION",
                    f"Grain dimension {dimension!r} is not produced by a column mapping",
                    field=dimension,
                    blocking=True,
                )
            )

    for mapping in proposal.columns:
        source = profile_columns.get(mapping.source_column)
        if source is None:
            issues.append(
                _validation_issue(
                    "UNKNOWN_SOURCE_COLUMN",
                    f"Source column {mapping.source_column!r} is not present in the profile",
                    field=mapping.source_column,
                    blocking=True,
                )
            )
            continue
        transformation = get_transformation(mapping.transformation)
        if transformation is None:
            issues.append(
                _validation_issue(
                    "UNKNOWN_TRANSFORMATION",
                    f"Transformation {mapping.transformation!r} is not allowlisted",
                    field=mapping.source_column,
                    blocking=True,
                )
            )
        elif (
            source.non_null_count > 0 and source.inferred_type not in transformation.accepted_types
        ):
            issues.append(
                _validation_issue(
                    "INCOMPATIBLE_TRANSFORMATION_TYPE",
                    (
                        f"{mapping.transformation!r} does not accept "
                        f"{source.inferred_type.value!r} input"
                    ),
                    field=mapping.source_column,
                    blocking=True,
                )
            )

    populated_roles = {
        column.semantic_role for column in profile.columns if column.non_null_count > 0
    }
    if SemanticRole.YEAR not in populated_roles:
        issues.append(
            _validation_issue(
                "MISSING_TIME_DIMENSION",
                "No populated year dimension is available",
                blocking=True,
            )
        )
    elif not mapped_targets.intersection({"year_roc", "year_gregorian"}):
        issues.append(
            _validation_issue(
                "MISSING_TIME_MAPPING",
                "The populated year dimension is not mapped to a canonical field",
                blocking=True,
            )
        )
    if not populated_roles.intersection({SemanticRole.DISTRICT_CODE, SemanticRole.DISTRICT_NAME}):
        issues.append(
            _validation_issue(
                "MISSING_GEOGRAPHY_DIMENSION",
                "No populated district dimension is available",
                blocking=True,
            )
        )
    elif not mapped_targets.intersection({"district_code", "district_name"}):
        issues.append(
            _validation_issue(
                "MISSING_GEOGRAPHY_MAPPING",
                "The populated district dimension is not mapped to a canonical field",
                blocking=True,
            )
        )
    if not proposal.metrics:
        issues.append(
            _validation_issue(
                "MISSING_METRIC",
                "No quantitative metric could be inferred",
                blocking=True,
            )
        )
    metric_sources = [metric.source_column for metric in proposal.metrics]
    if len(metric_sources) != len(set(metric_sources)):
        issues.append(
            _validation_issue(
                "DUPLICATE_METRIC_SOURCE",
                "A source column was assigned to more than one metric",
                blocking=True,
            )
        )
    metric_codes = [metric.metric_code for metric in proposal.metrics]
    if len(metric_codes) != len(set(metric_codes)):
        issues.append(
            _validation_issue(
                "DUPLICATE_METRIC_CODE",
                "Multiple source columns resolve to the same metric code",
                blocking=True,
            )
        )
    for metric in proposal.metrics:
        source = profile_columns.get(metric.source_column)
        if source is None:
            issues.append(
                _validation_issue(
                    "UNKNOWN_METRIC_SOURCE",
                    f"Metric source {metric.source_column!r} is not present in the profile",
                    field=metric.source_column,
                    blocking=True,
                )
            )
        elif source.inferred_type not in {PrimitiveType.INTEGER, PrimitiveType.FLOAT}:
            issues.append(
                _validation_issue(
                    "NON_NUMERIC_METRIC",
                    f"Metric source {metric.source_column!r} is not numeric",
                    field=metric.source_column,
                    blocking=True,
                )
            )
        if metric.unit_code is None:
            issues.append(
                _validation_issue(
                    "UNKNOWN_METRIC_UNIT",
                    f"Metric {metric.metric_code!r} requires an explicit unit",
                    field=metric.source_column,
                    blocking=True,
                )
            )
    if proposal.overall_confidence < options.review_confidence_threshold:
        issues.append(
            _validation_issue(
                "LOW_MAPPING_CONFIDENCE",
                (
                    f"Overall confidence {proposal.overall_confidence:.2f} is below "
                    f"the review threshold {options.review_confidence_threshold:.2f}"
                ),
            )
        )

    blocking = any(issue.blocking for issue in issues)
    requires_approval = proposal.requires_human_approval or bool(issues)
    return MappingValidationReport(
        valid=not blocking,
        overall_confidence=proposal.overall_confidence,
        requires_human_approval=requires_approval,
        issues=issues,
    )


def _map_canonical_column(
    column: ColumnProfile,
    rule: CanonicalFieldRule,
    profile: DatasetProfile,
) -> ColumnMapping:
    target_field = rule.target_field
    parameters: dict[str, object] = {}
    if rule.semantic_role == SemanticRole.YEAR:
        source_system = profile.time_coverage.source_year_system
        parameters["source_year_system"] = source_system or "unknown"
        if source_system in {"gregorian", "mixed"}:
            target_field = "year_gregorian"
    if rule.semantic_role == SemanticRole.AGE_LABEL:
        parameters["derived_fields"] = [
            "age_lower",
            "age_upper",
            "youth_relationship",
            "youth_weight",
            "is_estimated",
        ]

    transformation = get_transformation(rule.transformation)
    type_compatible = transformation is not None and (
        column.non_null_count == 0 or column.inferred_type in transformation.accepted_types
    )
    confidence = 0.99 if type_compatible else 0.65
    evidence = (
        f"Header {column.name!r} exactly matches the canonical alias registry; "
        f"profile inferred {column.inferred_type.value}"
    )
    return ColumnMapping(
        source_column=column.name,
        target_field=target_field,
        transformation=rule.transformation,
        transformation_parameters=parameters,
        confidence=confidence,
        evidence=evidence,
    )


def _map_metric(
    column: ColumnProfile,
    topic: str,
    population_scope: PopulationScope,
) -> MetricMapping:
    normalized = normalize_header(column.name)
    known = _KNOWN_METRICS.get(normalized)
    if known is None:
        metric_code = _slug_metric_code(column.name)
        unit_code = _infer_unit(column.name)
        aggregation_method = _infer_aggregation(column.name, unit_code)
        confidence = 0.70 if unit_code is not None else 0.50
        evidence = (
            f"Column is numeric and was profiled as a metric; unit confidence is "
            f"{'known' if unit_code else 'unknown'}"
        )
    else:
        metric_code, unit_code, aggregation_method = known
        confidence = 0.95 if unit_code is not None else 0.75
        evidence = f"Header {column.name!r} matches the known metric registry"

    if normalized in {"人數", "count"} and topic in _TOPIC_METRIC_CODES:
        metric_code = _TOPIC_METRIC_CODES[topic]
    return MetricMapping(
        source_column=column.name,
        metric_code=metric_code,
        unit_code=unit_code,
        population_scope=population_scope,
        aggregation_method=aggregation_method,
        confidence=confidence,
        evidence=evidence,
    )


def _select_grain_dimensions(
    candidates: list[tuple[str, CanonicalFieldRule]],
) -> list[str]:
    dimensions = [target for target, _ in candidates]
    if "district_code" in dimensions and "district_name" in dimensions:
        dimensions.remove("district_name")
    if "age_label_original" in dimensions:
        dimensions = [
            dimension for dimension in dimensions if dimension not in {"age_lower", "age_upper"}
        ]
    return list(dict.fromkeys(dimensions))


def _infer_topic(profile: DatasetProfile) -> str:
    targets = {
        rule.target_field
        for column in profile.columns
        if (rule := find_field_rule(column.name)) is not None
    }
    normalized_headers = {normalize_header(column.name) for column in profile.columns}
    if "jobseekers" in normalized_headers:
        return "employment"
    if "direction" in targets and "counterpart_region" in targets:
        return "migration"
    if "initial_registration_reason" in targets:
        return "household_registration"
    if "event_code" in targets or "marriage_type" in targets:
        return "marriage_events"
    if "education_code" in targets:
        return "education"
    if "marital_status_code" in targets:
        return "marriage"
    if "source_topic" in targets and "source_dataset_name" in targets:
        return "generic_open_data"
    if any(
        "所得" in column.name or "income" in column.name.casefold() for column in profile.columns
    ):
        return "income"
    if any(target in targets for target in {"age_label_original", "age_lower", "age_upper"}):
        return "population"
    return "unknown"


def _slug_metric_code(value: str) -> str:
    known = _KNOWN_METRICS.get(normalize_header(value))
    if known is not None:
        return known[0]
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    if ascii_slug and ascii_slug[0].isalpha():
        return ascii_slug
    return "unmapped_metric"


def _infer_unit(header: str) -> str | None:
    normalized = normalize_header(header)
    if any(token in normalized for token in ("人數", "人口", "count", "jobseekers")):
        return "persons"
    if any(token in normalized for token in ("戶數", "household")):
        return "households"
    if any(token in normalized for token in ("百分比", "percent", "率")):
        return "percent"
    return None


def _infer_aggregation(header: str, unit_code: str | None) -> str:
    normalized = normalize_header(header)
    if "中位" in normalized or "median" in normalized:
        return "median"
    if "平均" in normalized or "average" in normalized or "mean" in normalized:
        return "mean"
    if unit_code == "percent" or "ratio" in normalized:
        return "ratio"
    if unit_code in {"persons", "households"}:
        return "sum"
    return "not_additive"


def _validation_issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
    blocking: bool = False,
) -> MappingValidationIssue:
    return MappingValidationIssue(
        code=code,
        message=message,
        severity=WarningSeverity.ERROR if blocking else WarningSeverity.WARNING,
        field=field,
        blocking=blocking,
    )
