"""Canonical field and transformation registry used by profiling and mapping."""

import re
from dataclasses import dataclass

from youth_compass.domain.types import PrimitiveType, SemanticRole


@dataclass(frozen=True, slots=True)
class CanonicalFieldRule:
    target_field: str
    semantic_role: SemanticRole
    data_type: PrimitiveType
    transformation: str
    grain_dimension: bool
    aliases: frozenset[str]


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-()/\uff08\uff09]+", "", value.strip().casefold())


def _aliases(*values: str) -> frozenset[str]:
    return frozenset(normalize_header(value) for value in values)


CANONICAL_FIELD_RULES = (
    CanonicalFieldRule(
        "year_roc",
        SemanticRole.YEAR,
        PrimitiveType.INTEGER,
        "parse_year",
        True,
        _aliases("年", "年度", "民國年", "year", "stat_year", "report_year"),
    ),
    CanonicalFieldRule(
        "month",
        SemanticRole.MONTH,
        PrimitiveType.INTEGER,
        "parse_month",
        True,
        _aliases("月", "月份", "month", "stat_month", "report_month"),
    ),
    CanonicalFieldRule(
        "district_code",
        SemanticRole.DISTRICT_CODE,
        PrimitiveType.STRING,
        "normalize_district_code",
        True,
        _aliases("區代碼", "行政區代碼", "district_code", "area_code"),
    ),
    CanonicalFieldRule(
        "district_name",
        SemanticRole.DISTRICT_NAME,
        PrimitiveType.STRING,
        "normalize_district",
        True,
        _aliases("區", "行政區", "鄉鎮市區", "district", "district_name", "area", "area_name"),
    ),
    CanonicalFieldRule(
        "age_label_original",
        SemanticRole.AGE_LABEL,
        PrimitiveType.STRING,
        "parse_age_range",
        True,
        _aliases("年齡", "年齡標籤", "年齡組", "age", "age_group", "age_label"),
    ),
    CanonicalFieldRule(
        "age_lower",
        SemanticRole.AGE_LOWER,
        PrimitiveType.INTEGER,
        "parse_integer",
        True,
        _aliases("年齡下限", "age_lower", "age_min", "min_age"),
    ),
    CanonicalFieldRule(
        "age_upper",
        SemanticRole.AGE_UPPER,
        PrimitiveType.INTEGER,
        "parse_integer",
        True,
        _aliases("年齡上限", "age_upper", "age_max", "max_age"),
    ),
    CanonicalFieldRule(
        "gender_code",
        SemanticRole.GENDER,
        PrimitiveType.STRING,
        "normalize_gender",
        True,
        _aliases("性別", "gender", "sex"),
    ),
    CanonicalFieldRule(
        "education_code",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_education",
        True,
        _aliases("教育程度", "education", "education_level"),
    ),
    CanonicalFieldRule(
        "education_order",
        SemanticRole.DIMENSION,
        PrimitiveType.INTEGER,
        "parse_integer",
        False,
        _aliases("教育程度排序", "education_order", "education_sort_order"),
    ),
    CanonicalFieldRule(
        "graduation_status",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_graduation_status",
        True,
        _aliases("畢肄業", "graduation_status"),
    ),
    CanonicalFieldRule(
        "marital_status_code",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_marital_status",
        True,
        _aliases("婚姻狀況", "marital_status"),
    ),
    CanonicalFieldRule(
        "same_sex_marriage",
        SemanticRole.DIMENSION,
        PrimitiveType.BOOLEAN,
        "normalize_boolean",
        True,
        _aliases("是否同性婚", "same_sex_marriage"),
    ),
    CanonicalFieldRule(
        "direction",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_direction",
        True,
        _aliases("方向", "direction"),
    ),
    CanonicalFieldRule(
        "counterpart_region",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_text",
        True,
        _aliases("對象地區", "counterpart_region"),
    ),
    CanonicalFieldRule(
        "initial_registration_reason",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_text",
        True,
        _aliases("初設原因", "initial_registration_reason"),
    ),
    CanonicalFieldRule(
        "event_code",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_event",
        True,
        _aliases("事件", "event", "event_code"),
    ),
    CanonicalFieldRule(
        "marriage_type",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_marriage_type",
        True,
        _aliases("婚姻類型", "marriage_type"),
    ),
    CanonicalFieldRule(
        "source_topic",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_text",
        True,
        _aliases("主題", "topic"),
    ),
    CanonicalFieldRule(
        "source_agency",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_text",
        True,
        _aliases("機關", "agency", "organization"),
    ),
    CanonicalFieldRule(
        "source_dataset_name",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_text",
        True,
        _aliases("資料集", "dataset", "dataset_name"),
    ),
    CanonicalFieldRule(
        "youth_relationship",
        SemanticRole.DIMENSION,
        PrimitiveType.STRING,
        "normalize_youth_relationship",
        False,
        _aliases("青年關係", "youth_relationship"),
    ),
    CanonicalFieldRule(
        "youth_weight",
        SemanticRole.DIMENSION,
        PrimitiveType.FLOAT,
        "parse_float",
        False,
        _aliases("青年權重", "youth_weight"),
    ),
)

_BY_ALIAS = {alias: rule for rule in CANONICAL_FIELD_RULES for alias in rule.aliases}

_METRIC_HINTS = frozenset(
    normalize_header(value)
    for value in (
        "人數",
        "人口",
        "所得",
        "收入",
        "薪資",
        "戶數",
        "單位數",
        "count",
        "value",
        "population",
        "income",
        "salary",
        "job_seekers",
    )
)


def find_field_rule(source_header: str) -> CanonicalFieldRule | None:
    return _BY_ALIAS.get(normalize_header(source_header))


def header_has_metric_hint(source_header: str) -> bool:
    normalized = normalize_header(source_header)
    return any(hint in normalized for hint in _METRIC_HINTS)
