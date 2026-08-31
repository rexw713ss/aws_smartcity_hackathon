import pytest

from youth_compass.mapping.time import ParsedYear, parse_year


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (115, ParsedYear("115", 115, 2026, "roc")),
        ("民國 115 年", ParsedYear("民國 115 年", 115, 2026, "roc")),
        (2025, ParsedYear("2025", 114, 2025, "gregorian")),
        ("2025年", ParsedYear("2025年", 114, 2025, "gregorian")),
    ],
)
def test_parse_year(source: object, expected: ParsedYear) -> None:
    assert parse_year(source) == expected


@pytest.mark.parametrize("source", [None, "", "year 115", 0, 301, 1800, 2500])
def test_parse_year_rejects_invalid_values(source: object) -> None:
    assert parse_year(source) is None
