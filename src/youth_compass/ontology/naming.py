"""Readable labels for the slug identifiers the pipeline carries internally.

Feature values, candidate sites, and metrics are keyed by machine identifiers
(`site-linkou-center`, `ev_demand_proxy`). Those keys are correct for joins and
citations, but a person reading a chart axis should see "Site Linkou Center",
not the key. Nothing here changes a value or a join key: it only derives the
label shown beside one.

Naming is derived, never invented. A token that names a New Taipei district is
replaced by that district's published spelling, so one district never prints as
two places; every other token is only re-cased. An identifier that
carries no words yields itself rather than a guess.
"""

import re

from youth_compass.ontology.districts import (
    NameLanguage,
    localized_district_name,
    resolve_district_name,
)

# Codes whose letters are read out rather than pronounced. Casing these by the
# ordinary rule would print "Ev demand proxy", which reads as a typo.
_ACRONYMS = frozenset(
    {"ai", "api", "co2", "ev", "gdp", "h3", "id", "km", "ntd", "pm25", "uri", "url"}
)
_SEPARATORS = re.compile(r"[-_\s]+")
_MACHINE_SEPARATOR = re.compile(r"[-_]")
_GENERIC_ENTITY_PREFIXES = frozenset({"candidate", "location", "site"})
_HAN = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u1ef9]+")
_RESPONSE_LANGUAGE_MARKER = re.compile(r"^\[\[yc-response-language:(en|zh-TW)\]\]\n")
_ENGLISH_CUES = frozenset(
    {
        "compare",
        "district",
        "from",
        "how",
        "in",
        "me",
        "population",
        "show",
        "the",
        "to",
        "trend",
        "what",
    }
)
# Follow-up turns are short, so the cue has to be in the question itself: "Còn
# Linkou thì sao?" carries no topic word and would otherwise fall through to the
# English default and answer a Vietnamese question in English. Almost every
# entry is diacritic-bearing, which is what keeps it from colliding with an
# English word; "so" and "sao" are kept because neither is English either.
_VIETNAMESE_CUES = frozenset(
    {
        "cho",
        "chỉ",
        "còn",
        "dân",
        "giới",
        "đến",
        "hướng",
        "khu",
        "lấy",
        "nào",
        "nghiệp",
        "ngoái",
        "nhóm",
        "nữ",
        "năm",
        "quận",
        "sao",
        "sánh",
        "so",
        "số",
        "thất",
        "thì",
        "thế",
        "tuổi",
        "tôi",
        "từ",
        "và",
        "với",
        "xem",
        "xu",
        "ở",
    }
)


def question_language(question: str) -> NameLanguage:
    """Detect the instruction language without letting a place name decide it.

    District names are often pasted in a different script from the surrounding
    request. Lexical cues therefore win over script detection: ``Show ... in
    板橋區`` is English, while ``板橋區人口趨勢如何`` remains Traditional Chinese.
    """

    marker = _RESPONSE_LANGUAGE_MARKER.match(question)
    if marker is not None:
        return NameLanguage.ZH_HANT if marker.group(1) == "zh-TW" else NameLanguage.ENGLISH

    words = [match.group().casefold() for match in _LATIN_WORD.finditer(question)]
    english = sum(word in _ENGLISH_CUES for word in words)
    vietnamese = sum(word in _VIETNAMESE_CUES for word in words)
    if english or vietnamese:
        return NameLanguage.VIETNAMESE if vietnamese > english else NameLanguage.ENGLISH
    if _HAN.search(question):
        return NameLanguage.ZH_HANT
    return NameLanguage.ENGLISH


def force_question_language(question: str, language: str | None) -> str:
    """Attach a trusted internal response-language override after query planning."""

    if language not in {"en", "zh-TW"}:
        return question
    return f"[[yc-response-language:{language}]]\n{visible_question(question)}"


def visible_question(question: str) -> str:
    """Remove the internal response-language marker before display or external I/O."""

    return _RESPONSE_LANGUAGE_MARKER.sub("", question, count=1)


def humanize_code(code: str) -> str:
    """Label a snake_case code as a sentence: `ev_demand_proxy` -> `EV demand proxy`.

    Used for metric and feature codes, which name a quantity rather than a
    place, so only the first word is capitalized.
    """

    tokens = [token for token in _SEPARATORS.split(code.strip()) if token]
    if not tokens:
        return code
    words = [
        _acronym(token) or (token.capitalize() if index == 0 else token.lower())
        for index, token in enumerate(tokens)
    ]
    return " ".join(words)


def display_name(identifier: str, language: NameLanguage = NameLanguage.ENGLISH) -> str:
    """Label an entity identifier: `site-linkou-center` -> `Site Linkou Center`.

    An identifier that names a district on its own is returned in the requested
    language, so a question asked in Chinese keeps Chinese district names. A
    compound site identifier is title-cased in place; its district token is
    normalized to the published English spelling rather than translated, which
    keeps one label in one script.
    """

    raw = identifier.strip()
    if not raw:
        return identifier
    district = resolve_district_name(raw).district
    if district is not None:
        return localized_district_name(district.code, language) or district.name
    tokens = [token for token in _SEPARATORS.split(raw) if token]
    if not tokens:
        return identifier
    # Storage IDs often namespace a real venue as `site-linkou-center`. Once a
    # district token makes the location unambiguous, the namespace is metadata,
    # not part of the venue's name. Keep it for opaque IDs such as `site-a`.
    if (
        len(tokens) > 2
        and tokens[0].casefold() in _GENERIC_ENTITY_PREFIXES
        and any(
            resolve_district_name(token).district is not None
            for token in tokens[1:]
            if not token.isdigit()
        )
    ):
        tokens = tokens[1:]
    return " ".join(_entity_token(token) for token in tokens)


def readable_entity_name(
    identifier: str,
    published_name: str | None = None,
    language: NameLanguage = NameLanguage.ENGLISH,
) -> str:
    """Choose a formal reader-facing entity name without exposing a slug.

    A populated ``entity_name`` is not automatically trustworthy as display
    copy: several source datasets repeat their machine identifier in that
    field. Preserve a genuinely authored name, but derive one when the value is
    the identifier, contains machine separators, or is wholly lower-case.
    """

    name = published_name.strip() if published_name else ""
    if not name:
        return display_name(identifier, language)
    # A source-authored district label is trustworthy as identity, but its
    # script is not authoritative for presentation. Localize it to the language
    # of the request so an English answer never leaks a Chinese row label.
    published_district = resolve_district_name(name).district
    if published_district is not None:
        return localized_district_name(published_district.code, language) or name
    if (
        name.casefold() == identifier.strip().casefold()
        or _MACHINE_SEPARATOR.search(name)
        or bool(re.fullmatch(r"[a-z0-9 ]+", name))
    ):
        return display_name(name, language)
    return name


def readable_feature_name(code: str, published_name: str | None = None) -> str:
    """Choose authored feature copy, repairing code-like source labels."""

    name = published_name.strip() if published_name else ""
    if not name:
        return humanize_code(code)
    if name.casefold() == code.strip().casefold() or _MACHINE_SEPARATOR.search(name):
        return humanize_code(name)
    return name


def _entity_token(token: str) -> str:
    acronym = _acronym(token)
    if acronym is not None:
        return acronym
    # A bare number inside a compound identifier is a sequence, not a district
    # code, so only spelled-out tokens are matched against the dictionary.
    district = None if token.isdigit() else resolve_district_name(token).district
    if district is not None:
        return localized_district_name(district.code, NameLanguage.ENGLISH) or token
    return token if token[:1].isupper() else token.capitalize()


def _acronym(token: str) -> str | None:
    return token.upper() if token.casefold() in _ACRONYMS else None
