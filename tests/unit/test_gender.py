import pytest

from youth_compass.mapping.gender import normalize_gender


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("M", "male"),
        ("male", "male"),
        ("男", "male"),
        ("F", "female"),
        ("Female", "female"),
        ("女", "female"),
        ("其他", "other"),
        ("unknown", "unknown"),
    ],
)
def test_normalize_gender(source: object, expected: str) -> None:
    assert normalize_gender(source) == expected


@pytest.mark.parametrize("source", [None, "", "X", "未提供"])
def test_unknown_gender_returns_none(source: object) -> None:
    assert normalize_gender(source) is None
