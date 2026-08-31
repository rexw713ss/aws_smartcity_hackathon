from youth_compass.domain.types import PrimitiveType, SemanticRole
from youth_compass.mapping.registry import (
    find_field_rule,
    header_has_metric_hint,
    normalize_header,
)
from youth_compass.mapping.transform_registry import get_transformation


def test_header_normalization_handles_common_separators() -> None:
    assert normalize_header(" District_Name (區) ") == "districtname區"


def test_registry_resolves_english_and_chinese_aliases() -> None:
    english = find_field_rule("age_group")
    chinese = find_field_rule("行政區")

    assert english is not None
    assert english.target_field == "age_label_original"
    assert english.semantic_role == SemanticRole.AGE_LABEL
    assert chinese is not None
    assert chinese.target_field == "district_name"


def test_metric_hints_do_not_classify_arbitrary_numeric_headers() -> None:
    assert header_has_metric_hint("job_seekers") is True
    assert header_has_metric_hint("平均所得") is True
    assert header_has_metric_hint("opaque_number") is False


def test_transformation_registry_is_an_explicit_allowlist() -> None:
    transformation = get_transformation("parse_year")

    assert transformation is not None
    assert PrimitiveType.INTEGER in transformation.accepted_types
    assert get_transformation("execute_arbitrary_python") is None
