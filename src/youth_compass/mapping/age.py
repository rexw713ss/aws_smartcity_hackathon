"""Age-range parsing and inclusive youth overlap calculation."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class YouthRelationship(StrEnum):
    FULLY_WITHIN = "fully_within"
    PARTIALLY_OVERLAPS = "partially_overlaps"
    UNRELATED = "unrelated"
    NO_AGE_DIMENSION = "no_age_dimension"
    UNDEFINED = "undefined"


@dataclass(frozen=True, slots=True)
class AgeRange:
    original: str
    lower: int
    upper: int | None


@dataclass(frozen=True, slots=True)
class YouthOverlap:
    relationship: YouthRelationship
    weight: Decimal | None
    is_estimated: bool


_RANGE_PATTERN = re.compile(r"(\d{1,3})\s*(?:~|\uff5e|-|至)\s*(\d{1,3})\s*歲?")
_SINGLE_PATTERN = re.compile(r"(\d{1,3})\s*歲")
_UNDER_PATTERN = re.compile(r"未滿\s*(\d{1,3})\s*歲")
_OVER_PATTERN = re.compile(r"(\d{1,3})\s*歲?\s*(?:以上|及以上)")


def parse_age_range(value: object) -> AgeRange | None:
    if value is None:
        return None
    original = str(value).strip()
    if not original:
        return None

    match = _RANGE_PATTERN.fullmatch(original)
    if match:
        lower, upper = map(int, match.groups())
        if lower <= upper:
            return AgeRange(original, lower, upper)
        return None

    match = _SINGLE_PATTERN.fullmatch(original)
    if match:
        age = int(match.group(1))
        return AgeRange(original, age, age)

    match = _UNDER_PATTERN.fullmatch(original)
    if match:
        upper = int(match.group(1)) - 1
        return AgeRange(original, 0, upper) if upper >= 0 else None

    match = _OVER_PATTERN.fullmatch(original)
    if match:
        return AgeRange(original, int(match.group(1)), None)

    if original.isdigit():
        age = int(original)
        return AgeRange(original, age, age)
    return None


def youth_overlap(
    age_range: AgeRange,
    youth_lower: int = 18,
    youth_upper: int = 35,
) -> YouthOverlap:
    """Calculate inclusive overlap with the 18-35 youth definition."""

    lower, upper = age_range.lower, age_range.upper
    if upper is None:
        if lower > youth_upper:
            return YouthOverlap(YouthRelationship.UNRELATED, Decimal("0"), False)
        return YouthOverlap(YouthRelationship.UNDEFINED, None, True)

    overlap = max(0, min(upper, youth_upper) - max(lower, youth_lower) + 1)
    interval = upper - lower + 1
    if overlap == 0:
        return YouthOverlap(YouthRelationship.UNRELATED, Decimal("0"), False)
    if overlap == interval:
        return YouthOverlap(YouthRelationship.FULLY_WITHIN, Decimal("1"), False)
    weight = (Decimal(overlap) / Decimal(interval)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return YouthOverlap(YouthRelationship.PARTIALLY_OVERLAPS, weight, True)
