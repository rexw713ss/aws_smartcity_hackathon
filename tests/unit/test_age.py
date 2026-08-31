from decimal import Decimal

import pytest

from youth_compass.mapping.age import (
    AgeRange,
    YouthRelationship,
    parse_age_range,
    youth_overlap,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("18歲", AgeRange("18歲", 18, 18)),
        ("15~19歲", AgeRange("15~19歲", 15, 19)),
        ("15\uff5e19歲", AgeRange("15\uff5e19歲", 15, 19)),
        ("35-39", AgeRange("35-39", 35, 39)),
        ("未滿15歲", AgeRange("未滿15歲", 0, 14)),
        ("100歲以上", AgeRange("100歲以上", 100, None)),
        ("22", AgeRange("22", 22, 22)),
    ],
)
def test_parse_age_range(label: str, expected: AgeRange) -> None:
    assert parse_age_range(label) == expected


@pytest.mark.parametrize("label", ["", "unknown", "19~15歲", None])
def test_parse_age_range_rejects_invalid_values(label: object) -> None:
    assert parse_age_range(label) is None


@pytest.mark.parametrize(
    ("label", "relationship", "weight", "is_estimated"),
    [
        ("15-19", YouthRelationship.PARTIALLY_OVERLAPS, Decimal("0.4000"), True),
        ("20-24", YouthRelationship.FULLY_WITHIN, Decimal("1"), False),
        ("35-39", YouthRelationship.PARTIALLY_OVERLAPS, Decimal("0.2000"), True),
        ("0-14", YouthRelationship.UNRELATED, Decimal("0"), False),
        ("36-40", YouthRelationship.UNRELATED, Decimal("0"), False),
    ],
)
def test_youth_overlap(
    label: str,
    relationship: YouthRelationship,
    weight: Decimal,
    is_estimated: bool,
) -> None:
    age_range = parse_age_range(label)
    assert age_range is not None
    result = youth_overlap(age_range)
    assert result.relationship == relationship
    assert result.weight == weight
    assert result.is_estimated is is_estimated


def test_open_ended_overlap_is_undefined_when_boundary_intersects_youth() -> None:
    result = youth_overlap(AgeRange("30歲以上", 30, None))
    assert result.relationship == YouthRelationship.UNDEFINED
    assert result.weight is None
    assert result.is_estimated is True
