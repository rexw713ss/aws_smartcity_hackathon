"""ROC and Gregorian calendar normalization."""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedYear:
    original: str
    year_roc: int
    year_gregorian: int
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
