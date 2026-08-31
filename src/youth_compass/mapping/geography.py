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
