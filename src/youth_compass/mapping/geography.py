"""Canonical New Taipei City district dictionary."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class District:
    code: str
    name: str


_DISTRICT_NAMES = (
    "板橋區",
    "三重區",
    "中和區",
    "永和區",
    "新莊區",
    "新店區",
    "土城區",
    "蘆洲區",
    "樹林區",
    "鶯歌區",
    "三峽區",
    "淡水區",
    "汐止區",
    "瑞芳區",
    "五股區",
    "泰山區",
    "林口區",
    "八里區",
    "深坑區",
    "石碇區",
    "坪林區",
    "三芝區",
    "石門區",
    "金山區",
    "萬里區",
    "平溪區",
    "雙溪區",
    "貢寮區",
    "烏來區",
)

DISTRICTS = tuple(
    District(code=f"{index:02d}", name=name) for index, name in enumerate(_DISTRICT_NAMES, start=1)
)
_BY_NAME = {district.name: district for district in DISTRICTS}
_BY_CODE = {district.code: district for district in DISTRICTS}


def _clean_name(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    for prefix in ("臺灣省新北市", "台灣省新北市", "新北市"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    if cleaned and not cleaned.endswith("區"):
        cleaned = f"{cleaned}區"
    return cleaned


CITY_CODE = "65000"
CITY_NAME = "新北市"
_CITY_ALIASES = frozenset({"新北市", "臺灣省新北市", "台灣省新北市", "全市", "65000"})


def is_city_scope(value: object) -> bool:
    """True when a geography value names New Taipei as a whole, not one district.

    City-wide statistics (the labour force survey, for one) are published only
    at this level. Recognizing the city explicitly keeps them apart from an
    unknown district name, which must still fail.
    """

    return value is not None and re.sub(r"\s+", "", str(value)) in _CITY_ALIASES


def normalize_district(value: object) -> District | None:
    """Resolve a district code or common New Taipei City name alias."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        numeric_code = Decimal(raw)
    except InvalidOperation:
        numeric_code = None
    if numeric_code is not None and numeric_code == numeric_code.to_integral_value():
        return _BY_CODE.get(f"{int(numeric_code):02d}")
    return _BY_NAME.get(_clean_name(raw))


def extract_district(value: object) -> District | None:
    """Resolve a district explicitly embedded in a New Taipei address or site."""

    exact = normalize_district(value)
    if exact is not None:
        return exact
    if value is None:
        return None
    compact = re.sub(r"\s+", "", str(value))
    matches = [district for district in DISTRICTS if district.name in compact]
    if len(matches) != 1:
        return None
    district = matches[0]
    scope_prefix = compact[: compact.index(district.name)]
    names_new_taipei = any(
        prefix in scope_prefix for prefix in ("新北市", "臺灣省新北市", "台灣省新北市")
    )
    if ("市" in scope_prefix or "縣" in scope_prefix) and not names_new_taipei:
        return None
    return district
