"""Multilingual name ontology for the 29 New Taipei City districts.

The canonical dictionary in `youth_compass.mapping.geography` resolves codes and
Traditional Chinese names, which is all the ingestion path ever sees. A question
typed by a person does not respect that: the same district is written 淡水區,
Tamsui, or Đạm Thủy depending on who is asking. This module is the one place
that maps those spellings onto the canonical code, so the rest of the system
keeps working with `District` only.

Matching is exact after folding (case, diacritics, separators, administrative
prefixes and suffixes). Fuzzy or substring matching is deliberately absent:
guessing that an unknown string means a district would silently attribute
statistics to the wrong place.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from youth_compass.mapping.geography import DISTRICTS, District, normalize_district


class NameLanguage(StrEnum):
    """Which spelling of a district name a caller used."""

    CODE = "code"
    ZH_HANT = "zh_hant"
    ENGLISH = "english"
    VIETNAMESE = "vietnamese"


@dataclass(frozen=True, slots=True)
class DistrictNames:
    """Every spelling this system recognizes for one district."""

    code: str
    zh_hant: str
    english: str
    vietnamese: str


@dataclass(frozen=True, slots=True)
class DistrictResolution:
    """Auditable outcome of resolving one user-supplied place name."""

    source_value: str
    district: District | None
    language: NameLanguage | None

    @property
    def resolved(self) -> bool:
        return self.district is not None


# Romanizations follow the Hanyu Pinyin spellings New Taipei City publishes in
# English, except 淡水 which the city writes Tamsui. Vietnamese names are the
# standard Sino-Vietnamese readings of the same characters.
_ROMANIZATIONS: tuple[tuple[str, str, str], ...] = (
    ("01", "Banqiao", "Bản Kiều"),
    ("02", "Sanchong", "Tam Trùng"),
    ("03", "Zhonghe", "Trung Hòa"),
    ("04", "Yonghe", "Vĩnh Hòa"),
    ("05", "Xinzhuang", "Tân Trang"),
    ("06", "Xindian", "Tân Điếm"),
    ("07", "Tucheng", "Thổ Thành"),
    ("08", "Luzhou", "Lô Châu"),
    ("09", "Shulin", "Thụ Lâm"),
    ("10", "Yingge", "Oanh Ca"),
    ("11", "Sanxia", "Tam Hiệp"),
    ("12", "Tamsui", "Đạm Thủy"),
    ("13", "Xizhi", "Tịch Chỉ"),
    ("14", "Ruifang", "Thụy Phương"),
    ("15", "Wugu", "Ngũ Cổ"),
    ("16", "Taishan", "Thái Sơn"),
    ("17", "Linkou", "Lâm Khẩu"),
    ("18", "Bali", "Bát Lý"),
    ("19", "Shenkeng", "Thâm Khanh"),
    ("20", "Shiding", "Thạch Đính"),
    ("21", "Pinglin", "Bình Lâm"),
    ("22", "Sanzhi", "Tam Chi"),
    ("23", "Shimen", "Thạch Môn"),
    ("24", "Jinshan", "Kim Sơn"),
    ("25", "Wanli", "Vạn Lý"),
    ("26", "Pingxi", "Bình Khê"),
    ("27", "Shuangxi", "Song Khê"),
    ("28", "Gongliao", "Cống Liêu"),
    ("29", "Wulai", "Ô Lai"),
)

# Extra spellings that are neither the canonical romanization nor a reading of
# the characters. Kept explicit so every accepted alias is reviewable.
_EXTRA_ENGLISH: dict[str, tuple[str, ...]] = {
    "12": ("Danshui", "Tanshui"),
    "02": ("Sanchung",),
    "03": ("Chungho",),
    "05": ("Hsinchuang",),
    "06": ("Hsintien",),
    "13": ("Hsichih",),
}

# \u2019 is the curly apostrophe keyboards insert; \u00b7 the interpunct in
# some romanizations. Both are separators here, never part of a name.
_SEPARATORS = re.compile("[\\s\\-_.,'\u2019\u00b7]+")
# Administrative words a person may add around the name in any of the three
# languages. Stripped after folding, so only the ASCII forms appear here.
_AFFIXES: tuple[str, ...] = ("district", "quan", "huyen", "newtaipeicity", "newtaipei")


def _strip_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _fold(value: str) -> str:
    """Reduce one spelling to its comparison key.

    Case, diacritics, separators, and administrative affixes carry no meaning
    here: `Đạm Thủy`, `dam thuy`, and `Tamsui District` must all reach the same
    key. `đ` is normalized explicitly because NFD does not decompose it.
    """

    folded = _strip_marks(value.strip().casefold()).replace("đ", "d")
    folded = _SEPARATORS.sub("", folded)
    folded = folded.removesuffix("區").removesuffix("区")
    for affix in _AFFIXES:
        if folded.startswith(affix) and len(folded) > len(affix):
            folded = folded[len(affix) :]
        if folded.endswith(affix) and len(folded) > len(affix):
            folded = folded[: -len(affix)]
    return folded


def _build() -> tuple[
    tuple[DistrictNames, ...],
    dict[str, DistrictNames],
    dict[str, tuple[str, NameLanguage]],
]:
    by_code = {district.code: district for district in DISTRICTS}
    names: list[DistrictNames] = []
    aliases: dict[str, tuple[str, NameLanguage]] = {}
    for code, english, vietnamese in _ROMANIZATIONS:
        district = by_code[code]
        entry = DistrictNames(
            code=code, zh_hant=district.name, english=english, vietnamese=vietnamese
        )
        names.append(entry)
        spellings: list[tuple[str, NameLanguage]] = [
            (english, NameLanguage.ENGLISH),
            *((extra, NameLanguage.ENGLISH) for extra in _EXTRA_ENGLISH.get(code, ())),
            (vietnamese, NameLanguage.VIETNAMESE),
        ]
        for spelling, language in spellings:
            key = _fold(spelling)
            existing = aliases.get(key)
            if existing is not None and existing[0] != code:
                raise RuntimeError(f"district alias {spelling!r} is ambiguous")
            aliases[key] = (code, language)
    ordered = tuple(names)
    return ordered, {item.code: item for item in ordered}, aliases


DISTRICT_NAMES, _NAMES_BY_CODE, _ALIASES = _build()


def resolve_district_name(value: object) -> DistrictResolution:
    """Resolve a code, a Chinese name, or an English or Vietnamese spelling.

    The canonical resolver runs first so ingestion behaviour is unchanged; the
    multilingual table is only consulted when that returns nothing.
    """

    raw = "" if value is None else str(value).strip()
    if not raw:
        return DistrictResolution(source_value=raw, district=None, language=None)
    canonical = normalize_district(raw)
    if canonical is not None:
        digits = any(char.isdigit() for char in raw)
        language = NameLanguage.CODE if digits else NameLanguage.ZH_HANT
        return DistrictResolution(source_value=raw, district=canonical, language=language)
    hit = _ALIASES.get(_fold(raw))
    if hit is None:
        return DistrictResolution(source_value=raw, district=None, language=None)
    code, language = hit
    district = next(item for item in DISTRICTS if item.code == code)
    return DistrictResolution(source_value=raw, district=district, language=language)


# Letters only, across the three scripts a question may mix. The Latin range
# ends before CJK, so Chinese names are scanned separately as substrings.
_LATIN_WORDS = re.compile(r"[A-Za-z\u00c0-\u1ef9]+")
# "Tam Hiệp" and "Bản Kiều" are two words; every English spelling is one.
_MAX_NAME_WORDS = 2


def extract_districts(text: str) -> tuple[District, ...]:
    """Find the districts a person named in free text, in the order written.

    Chinese names are matched as substrings because the script has no word
    separators. Latin text is matched word by word, trying the two-word form
    first so a Vietnamese name is not split. Matching is exact after folding,
    the same rule `resolve_district_name` uses: a name this dictionary does not
    contain yields nothing rather than a nearest guess.
    """

    if not text:
        return ()
    first_seen: dict[str, int] = {}

    for names in DISTRICT_NAMES:
        for form in (names.zh_hant, names.zh_hant.removesuffix("區")):
            position = text.find(form)
            if position >= 0:
                first_seen.setdefault(names.code, position)
                break

    words = list(_LATIN_WORDS.finditer(text))
    for index, word in enumerate(words):
        window = words[index : index + _MAX_NAME_WORDS]
        # Longest first: "Tam Hiệp" must win over the bare word "Tam".
        for size in range(len(window), 0, -1):
            phrase = " ".join(item.group() for item in window[:size])
            hit = _ALIASES.get(_fold(phrase))
            if hit is None:
                continue
            code = hit[0]
            if word.start() < first_seen.get(code, word.start() + 1):
                first_seen[code] = word.start()
            break

    by_code = {district.code: district for district in DISTRICTS}
    return tuple(by_code[code] for code, _ in sorted(first_seen.items(), key=lambda item: item[1]))


def district_spellings(value: object) -> tuple[str, ...]:
    """Return every identifier that may denote the district a value names.

    The original value comes first, so widening an identifier filter with this
    keeps matching data that is already keyed the caller's way. Expansion is
    only safe because no spelling maps to two districts; `_build` refuses to
    register an ambiguous alias.
    """

    raw = "" if value is None else str(value).strip()
    resolution = resolve_district_name(raw)
    if resolution.district is None:
        return (raw,) if raw else ()
    names = _NAMES_BY_CODE[resolution.district.code]
    spellings = (
        raw,
        names.code,
        names.zh_hant,
        names.english,
        names.english.casefold(),
        names.vietnamese,
    )
    return tuple(dict.fromkeys(item for item in spellings if item))


def district_names(code: str) -> DistrictNames | None:
    """Return every recognized spelling for a canonical district code."""

    return _NAMES_BY_CODE.get(code)


def localized_district_name(code: str, language: NameLanguage) -> str | None:
    """Return one spelling of a district, or None when the code is unknown."""

    entry = _NAMES_BY_CODE.get(code)
    if entry is None:
        return None
    if language is NameLanguage.ENGLISH:
        return entry.english
    if language is NameLanguage.VIETNAMESE:
        return entry.vietnamese
    if language is NameLanguage.ZH_HANT:
        return entry.zh_hant
    return entry.code
