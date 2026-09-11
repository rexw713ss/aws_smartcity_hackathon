"""Execution of allowlisted mappings against one source record."""

import math
from dataclasses import dataclass
from datetime import date

from youth_compass.domain.contracts import MappingProposal, PopulationScope
from youth_compass.mapping.age import AgeRange, YouthRelationship, youth_overlap
from youth_compass.mapping.gender import normalize_gender
from youth_compass.mapping.geography import District, normalize_district
from youth_compass.mapping.time import parse_year

_NULL_TOKENS = {"", "null", "none", "n/a", "na", "nan"}
_YOUTH_RELATIONSHIPS = {
    "完全落入": YouthRelationship.FULLY_WITHIN,
    "fully_within": YouthRelationship.FULLY_WITHIN,
    "部分重疊": YouthRelationship.PARTIALLY_OVERLAPS,
    "partially_overlaps": YouthRelationship.PARTIALLY_OVERLAPS,
    "不相關": YouthRelationship.UNRELATED,
    "unrelated": YouthRelationship.UNRELATED,
    "無年齡維度": YouthRelationship.NO_AGE_DIMENSION,
    "no_age_dimension": YouthRelationship.NO_AGE_DIMENSION,
    "未定義": YouthRelationship.UNDEFINED,
    "undefined": YouthRelationship.UNDEFINED,
}
_GRADUATION_STATUSES = {
    "畢業": "graduated",
    "肄業": "not_graduated",
    "未分": "unspecified",
    "graduated": "graduated",
    "not_graduated": "not_graduated",
    "unspecified": "unspecified",
}
_MARITAL_STATUSES = {
    "未婚": "unmarried",
    "有偶": "married",
    "離婚": "divorced",
    "喪偶": "widowed",
    "unmarried": "unmarried",
    "married": "married",
    "divorced": "divorced",
    "widowed": "widowed",
}
_DIRECTIONS = {
    "遷入": "inbound",
    "遷出": "outbound",
    "inbound": "inbound",
    "outbound": "outbound",
}
_EVENTS = {
    "結婚": "marriage",
    "離婚": "divorce",
    "出生": "birth",
    "marriage": "marriage",
    "divorce": "divorce",
    "birth": "birth",
}
_MARRIAGE_TYPES = {
    "相同性別": "same_sex",
    "不同性別": "different_sex",
    "same_sex": "same_sex",
    "different_sex": "different_sex",
}
_BOOLEAN_VALUES = {
    "1": True,
    "true": True,
    "yes": True,
    "是": True,
    "0": False,
    "false": False,
    "no": False,
    "否": False,
}
_TOTAL_TOKENS = {"合計", "總計", "全部", "all", "total", "grand_total"}


class RowTransformationError(ValueError):
    """A source row cannot satisfy its approved deterministic mapping."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class RowTransformationResult:
    observations: list[dict[str, object]]
    filter_reason: str | None


@dataclass(frozen=True, slots=True)
class LineageContext:
    source_row_number: int
    source_sha256: str
    dataset_id: str
    dataset_version: str
    mapping_version: str
    transformation_version: str


def transform_row(
    row: dict[str, str],
    proposal: MappingProposal,
    lineage: LineageContext,
) -> RowTransformationResult:
    values = _base_values(proposal, lineage)
    source_relationship: YouthRelationship | None = None
    source_weight: float | None = None

    for mapping in proposal.columns:
        raw = row.get(mapping.source_column)
        if _is_null(raw):
            continue
        assert raw is not None
        if mapping.target_field == "youth_relationship":
            source_relationship = _normalize_youth_relationship(raw, mapping.source_column)
            continue
        if mapping.target_field == "youth_weight":
            source_weight = _parse_float(raw, mapping.source_column)
            continue
        _apply_column_mapping(
            values,
            target=mapping.target_field,
            transformation=mapping.transformation,
            raw=raw,
            source_field=mapping.source_column,
        )

    relationship, weight, is_estimated = _derive_youth_fields(
        values,
        source_relationship,
        source_weight,
    )
    values["youth_relationship"] = relationship.value
    values["youth_weight"] = weight
    values["is_estimated"] = is_estimated
    _derive_period(values)
    _validate_grain(values, proposal)

    if _is_verified_total_row(row, proposal):
        return RowTransformationResult(observations=[], filter_reason="verified_total")

    youth_specific = any(
        metric.population_scope == PopulationScope.YOUTH_SPECIFIC for metric in proposal.metrics
    )
    if youth_specific and relationship == YouthRelationship.UNRELATED:
        return RowTransformationResult(observations=[], filter_reason="outside_youth_range")
    if youth_specific and relationship in {
        YouthRelationship.NO_AGE_DIMENSION,
        YouthRelationship.UNDEFINED,
    }:
        raise RowTransformationError(
            "UNRESOLVED_YOUTH_OVERLAP",
            "A youth-specific row must have a bounded age interval",
            "age_label_original",
        )

    observations: list[dict[str, object]] = []
    for metric in proposal.metrics:
        raw_metric = row.get(metric.source_column)
        if _is_null(raw_metric):
            continue
        assert raw_metric is not None
        original_value = _parse_float(raw_metric, metric.source_column)
        if metric.unit_code in {"persons", "households"} and original_value < 0:
            raise RowTransformationError(
                "NEGATIVE_ADDITIVE_METRIC",
                f"Additive metric {metric.metric_code!r} cannot be negative",
                metric.source_column,
            )
        metric_value = original_value
        metric_estimated = is_estimated
        if (
            relationship == YouthRelationship.PARTIALLY_OVERLAPS
            and weight is not None
            and metric.aggregation_method == "sum"
            and metric.unit_code in {"persons", "households"}
        ):
            metric_value *= weight
            metric_estimated = True
        observation = dict(values)
        observation.update(
            {
                "is_estimated": metric_estimated,
                "metric_code": metric.metric_code,
                "metric_value": metric_value,
                "metric_value_original": original_value,
                "unit_code": metric.unit_code,
                "aggregation_method": metric.aggregation_method,
                "population_scope": metric.population_scope.value,
            }
        )
        observations.append(observation)

    if not observations:
        raise RowTransformationError(
            "MISSING_METRIC_VALUE",
            "The source row has no mapped metric value",
        )
    return RowTransformationResult(observations=observations, filter_reason=None)


def _base_values(
    proposal: MappingProposal,
    lineage: LineageContext,
) -> dict[str, object]:
    return {
        "source_row_number": lineage.source_row_number,
        "source_sha256": lineage.source_sha256,
        "dataset_id": lineage.dataset_id,
        "dataset_version": lineage.dataset_version,
        "mapping_version": lineage.mapping_version,
        "transformation_version": lineage.transformation_version,
        "topic": proposal.topic,
        "dataset_role": proposal.dataset_role.value,
        "year_roc": None,
        "year_gregorian": None,
        "month": None,
        "period_start": None,
        "period_granularity": "unknown",
        "city_code": "65000",
        "city_name": "新北市",
        "district_code": None,
        "district_name": None,
        "geography_granularity": "unknown",
        "age_label_original": None,
        "age_lower": None,
        "age_upper": None,
        "youth_relationship": YouthRelationship.NO_AGE_DIMENSION.value,
        "youth_weight": 0.0,
        "is_estimated": False,
        "gender_code": None,
        "gender_label_original": None,
        "education_code": None,
        "education_order": None,
        "graduation_status": None,
        "marital_status_code": None,
        "same_sex_marriage": None,
        "direction": None,
        "counterpart_region": None,
        "initial_registration_reason": None,
        "event_code": None,
        "marriage_type": None,
        "source_topic": None,
        "source_agency": None,
        "source_dataset_name": None,
    }


def _apply_column_mapping(
    values: dict[str, object],
    *,
    target: str,
    transformation: str,
    raw: str,
    source_field: str,
) -> None:
    if transformation == "parse_year":
        parsed = parse_year(raw)
        if parsed is None:
            raise RowTransformationError(
                "INVALID_YEAR", f"Cannot parse year value {raw!r}", source_field
            )
        _set_consistent(values, "year_roc", parsed.year_roc, source_field)
        _set_consistent(values, "year_gregorian", parsed.year_gregorian, source_field)
        return
    if transformation == "parse_month":
        month = _parse_integer(raw, source_field)
        if not 1 <= month <= 12:
            raise RowTransformationError(
                "INVALID_MONTH", f"Month must be between 1 and 12, got {raw!r}", source_field
            )
        _set_consistent(values, target, month, source_field)
        return
    if transformation in {"normalize_district", "normalize_district_code"}:
        district = normalize_district(raw)
        if district is None:
            raise RowTransformationError(
                "UNKNOWN_DISTRICT", f"Unknown New Taipei district {raw!r}", source_field
            )
        _set_district(values, district, source_field)
        return
    if transformation == "parse_age_range":
        from youth_compass.mapping.age import parse_age_range

        age_range = parse_age_range(raw)
        if age_range is None:
            raise RowTransformationError(
                "INVALID_AGE_RANGE", f"Cannot parse age range {raw!r}", source_field
            )
        values["age_label_original"] = age_range.original
        _set_consistent(values, "age_lower", age_range.lower, source_field)
        if age_range.upper is not None:
            _set_consistent(values, "age_upper", age_range.upper, source_field)
        return
    if transformation == "parse_integer":
        _set_consistent(values, target, _parse_integer(raw, source_field), source_field)
        return
    if transformation == "parse_float":
        _set_consistent(values, target, _parse_float(raw, source_field), source_field)
        return
    if transformation == "normalize_gender":
        normalized = normalize_gender(raw)
        if normalized is None:
            raise RowTransformationError(
                "UNKNOWN_GENDER", f"Unknown gender value {raw!r}", source_field
            )
        values["gender_label_original"] = raw.strip()
        _set_consistent(values, target, normalized, source_field)
        return
    if transformation == "normalize_education":
        _set_consistent(values, target, _normalize_text(raw), source_field)
        return
    if transformation == "normalize_graduation_status":
        normalized = _GRADUATION_STATUSES.get(raw.strip().casefold())
        if normalized is None:
            raise RowTransformationError(
                "UNKNOWN_GRADUATION_STATUS",
                f"Unknown graduation status {raw!r}",
                source_field,
            )
        _set_consistent(values, target, normalized, source_field)
        return
    if transformation == "normalize_marital_status":
        cleaned = raw.strip()
        base = cleaned.split("_", maxsplit=1)[0]
        normalized = _MARITAL_STATUSES.get(base.casefold())
        if normalized is None:
            raise RowTransformationError(
                "UNKNOWN_MARITAL_STATUS", f"Unknown marital status {raw!r}", source_field
            )
        _set_consistent(values, target, normalized, source_field)
        if "相同性別" in cleaned:
            _set_consistent(values, "same_sex_marriage", True, source_field)
        return
    if transformation == "normalize_boolean":
        normalized_bool = _BOOLEAN_VALUES.get(raw.strip().casefold())
        if normalized_bool is None:
            raise RowTransformationError(
                "INVALID_BOOLEAN", f"Cannot parse boolean value {raw!r}", source_field
            )
        _set_consistent(values, target, normalized_bool, source_field)
        return
    if transformation == "normalize_direction":
        _set_known_text(values, target, raw, source_field, _DIRECTIONS, "UNKNOWN_DIRECTION")
        return
    if transformation == "normalize_event":
        _set_known_text(values, target, raw, source_field, _EVENTS, "UNKNOWN_EVENT")
        return
    if transformation == "normalize_marriage_type":
        _set_known_text(values, target, raw, source_field, _MARRIAGE_TYPES, "UNKNOWN_MARRIAGE_TYPE")
        return
    if transformation == "normalize_text":
        _set_consistent(values, target, _normalize_text(raw), source_field)
        return
    raise RowTransformationError(
        "UNKNOWN_TRANSFORMATION",
        f"Transformation {transformation!r} is not executable",
        source_field,
    )


def _derive_youth_fields(
    values: dict[str, object],
    source_relationship: YouthRelationship | None,
    source_weight: float | None,
) -> tuple[YouthRelationship, float | None, bool]:
    lower = values.get("age_lower")
    upper = values.get("age_upper")
    relationship: YouthRelationship
    weight: float | None
    is_estimated: bool
    if lower is None and upper is None:
        relationship = YouthRelationship.NO_AGE_DIMENSION
        weight = 0.0
        is_estimated = False
    elif not isinstance(lower, int) or (upper is not None and not isinstance(upper, int)):
        raise RowTransformationError(
            "INCOMPLETE_AGE_RANGE", "Age bounds are incomplete", "age_label_original"
        )
    elif upper is not None and lower > upper:
        raise RowTransformationError(
            "INVALID_AGE_RANGE", "Age lower bound exceeds upper bound", "age_label_original"
        )
    else:
        overlap = youth_overlap(
            AgeRange(str(values.get("age_label_original") or lower), lower, upper)
        )
        relationship = overlap.relationship
        weight = float(overlap.weight) if overlap.weight is not None else None
        is_estimated = overlap.is_estimated

    if source_relationship is not None and source_relationship != relationship:
        raise RowTransformationError(
            "YOUTH_RELATIONSHIP_MISMATCH",
            f"Source relationship {source_relationship.value!r} conflicts with derived value "
            f"{relationship.value!r}",
            "youth_relationship",
        )
    if (
        source_weight is not None
        and weight is not None
        and not math.isclose(source_weight, weight, abs_tol=0.0001)
    ):
        raise RowTransformationError(
            "YOUTH_WEIGHT_MISMATCH",
            f"Source youth weight {source_weight} conflicts with derived weight {weight}",
            "youth_weight",
        )
    return relationship, weight, is_estimated


def _derive_period(values: dict[str, object]) -> None:
    year = values.get("year_gregorian")
    month = values.get("month")
    if isinstance(year, int):
        normalized_month = month if isinstance(month, int) else 1
        values["period_start"] = date(year, normalized_month, 1)
        values["period_granularity"] = "month" if month is not None else "year"
    if values.get("district_code") is not None:
        values["geography_granularity"] = "district"


def _validate_grain(values: dict[str, object], proposal: MappingProposal) -> None:
    for dimension in proposal.grain.dimensions:
        if values.get(dimension) is None:
            raise RowTransformationError(
                "MISSING_GRAIN_VALUE",
                f"Required grain dimension {dimension!r} is empty",
                dimension,
            )


def _is_verified_total_row(row: dict[str, str], proposal: MappingProposal) -> bool:
    grain_dimensions = set(proposal.grain.dimensions)
    for mapping in proposal.columns:
        if mapping.target_field not in grain_dimensions:
            continue
        raw = row.get(mapping.source_column)
        if raw is not None and raw.strip().casefold() in _TOTAL_TOKENS:
            return True
    return False


def _set_district(values: dict[str, object], district: District, source_field: str) -> None:
    _set_consistent(values, "district_code", district.code, source_field)
    _set_consistent(values, "district_name", district.name, source_field)


def _set_consistent(values: dict[str, object], key: str, value: object, source_field: str) -> None:
    existing = values.get(key)
    if existing is not None and existing != value:
        raise RowTransformationError(
            "CONFLICTING_CANONICAL_VALUE",
            f"Field {key!r} resolves to both {existing!r} and {value!r}",
            source_field,
        )
    values[key] = value


def _set_known_text(
    values: dict[str, object],
    target: str,
    raw: str,
    source_field: str,
    aliases: dict[str, str],
    error_code: str,
) -> None:
    normalized = aliases.get(raw.strip().casefold())
    if normalized is None:
        raise RowTransformationError(
            error_code, f"Unknown value {raw!r} for {target!r}", source_field
        )
    _set_consistent(values, target, normalized, source_field)


def _normalize_youth_relationship(raw: str, source_field: str) -> YouthRelationship:
    relationship = _YOUTH_RELATIONSHIPS.get(raw.strip().casefold())
    if relationship is None:
        raise RowTransformationError(
            "UNKNOWN_YOUTH_RELATIONSHIP",
            f"Unknown youth relationship {raw!r}",
            source_field,
        )
    return relationship


def _normalize_text(raw: str) -> str:
    return " ".join(raw.strip().split())


def _parse_integer(raw: str, source_field: str) -> int:
    cleaned = raw.strip().replace(",", "")
    try:
        parsed = float(cleaned)
    except ValueError as error:
        raise RowTransformationError(
            "INVALID_INTEGER", f"Cannot parse integer value {raw!r}", source_field
        ) from error
    if not math.isfinite(parsed) or not parsed.is_integer():
        raise RowTransformationError(
            "INVALID_INTEGER", f"Cannot parse integer value {raw!r}", source_field
        )
    return int(parsed)


def _parse_float(raw: str, source_field: str) -> float:
    try:
        parsed = float(raw.strip().replace(",", ""))
    except ValueError as error:
        raise RowTransformationError(
            "INVALID_NUMBER", f"Cannot parse numeric value {raw!r}", source_field
        ) from error
    if not math.isfinite(parsed):
        raise RowTransformationError(
            "INVALID_NUMBER", f"Numeric value {raw!r} is not finite", source_field
        )
    return parsed


def _is_null(raw: str | None) -> bool:
    return raw is None or raw.strip().casefold() in _NULL_TOKENS
