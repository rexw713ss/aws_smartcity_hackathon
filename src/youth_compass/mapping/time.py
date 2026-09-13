"""ROC and Gregorian calendar normalization."""

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ParsedYear:
    original: str
    year_roc: int
    year_gregorian: int
    detected_system: str


@dataclass(frozen=True, slots=True)
class ParsedCalendarDate:
    original: str
    year_roc: int
    year_gregorian: int
    month: int | None
    day: int | None
    detected_system: str


_YEAR_PATTERN = re.compile(r"(?:民國)?\s*(\d{2,4})\s*年?")


def parse_year(value: object) -> ParsedYear | None:
    """Parse a ROC or Gregorian year using conservative numeric boundaries."""

    if value is None:
        return None
    original = str(value).strip()
    if not original:
        return None
    match = _YEAR_PATTERN.fullmatch(original)
    if match is None:
        return None
    number = int(match.group(1))
    if 1 <= number <= 300:
        return ParsedYear(original, number, number + 1911, "roc")
    if 1912 <= number <= 2300:
        return ParsedYear(original, number - 1911, number, "gregorian")
    return None


def parse_compact_date(value: object) -> ParsedCalendarDate | None:
    """Parse official compact or slash/dash-separated ROC and Gregorian dates."""

    if value is None:
        return None
    original = str(value).strip()
    separated = re.fullmatch(r"(\d{2,4})([/-])(\d{1,2})\2(\d{1,2})", original)
    if separated is not None:
        year_token, _, month_token, day_token = separated.groups()
        source_year = int(year_token)
        month = int(month_token)
        day = int(day_token)
        year_digits = len(year_token)
    elif year_only := re.fullmatch(r"(\d{2,4})//", original):
        year_token = year_only.group(1)
        source_year = int(year_token)
        month = None
        day = None
        year_digits = len(year_token)
    elif original.isdigit() and len(original) in {7, 8}:
        year_digits = len(original) - 4
        source_year = int(original[:year_digits])
        month = int(original[year_digits : year_digits + 2])
        day = int(original[-2:])
    else:
        return None
    if year_digits <= 3:
        year_roc = source_year
        year_gregorian = source_year + 1911
        detected_system = "roc"
    else:
        year_gregorian = source_year
        year_roc = source_year - 1911
        detected_system = "gregorian"
    if year_roc < 1:
        return None
    try:
        date(year_gregorian, month or 1, day or 1)
    except ValueError:
        return None
    return ParsedCalendarDate(
        original,
        year_roc,
        year_gregorian,
        month,
        day,
        detected_system,
    )
