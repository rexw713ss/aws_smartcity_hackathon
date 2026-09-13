import pytest

from youth_compass.mapping.time import (
    ParsedCalendarDate,
    ParsedYear,
    parse_compact_date,
    parse_year,
)


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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1150105", ParsedCalendarDate("1150105", 115, 2026, 1, 5, "roc")),
        ("112/01/04", ParsedCalendarDate("112/01/04", 112, 2023, 1, 4, "roc")),
        ("112-1-4", ParsedCalendarDate("112-1-4", 112, 2023, 1, 4, "roc")),
        ("099//", ParsedCalendarDate("099//", 99, 2010, None, None, "roc")),
        (20250105, ParsedCalendarDate("20250105", 114, 2025, 1, 5, "gregorian")),
        ("2025/1/5", ParsedCalendarDate("2025/1/5", 114, 2025, 1, 5, "gregorian")),
    ],
)
def test_parse_compact_official_date(source: object, expected: ParsedCalendarDate) -> None:
    assert parse_compact_date(source) == expected


@pytest.mark.parametrize("source", [None, "", "1150230", "115/01-05", "0000101"])
def test_parse_compact_date_rejects_invalid_values(source: object) -> None:
    assert parse_compact_date(source) is None
