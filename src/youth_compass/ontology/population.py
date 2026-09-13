"""Demographic concept ontology: which population a count actually counts.

Taiwanese district statistics are published on two incompatible bases. The
household registration system counts people whose 戶籍 is in the district, which
is an administrative fact and may not be where they sleep. The resident series
counts usual residents (常住人口). Commuter and student districts differ
substantially between the two, so a series measured on one basis must never be
compared with, divided by, or ranked against a series measured on the other.

Nothing here infers a basis from a topic name. A metric is reported as UNKNOWN
unless the catalog text says which basis it uses, because a wrong assumption
here silently corrupts every derived rate.
"""

import re
import unicodedata
from enum import StrEnum


class RegistrationBasis(StrEnum):
    """Which population a metric counts."""

    REGISTERED_HOUSEHOLD = "registered_household"
    RESIDENT = "resident"
    UNKNOWN = "unknown"


_ASCII_TERMS: tuple[tuple[RegistrationBasis, tuple[str, ...]], ...] = (
    (
        RegistrationBasis.REGISTERED_HOUSEHOLD,
        (
            "registeredpopulation",
            "registeredhousehold",
            "householdregistration",
            "householdregistered",
            "deiurepopulation",
            "danhokhau",
            "dansohokhau",
            "hokhau",
        ),
    ),
    (
        RegistrationBasis.RESIDENT,
        (
            "residentpopulation",
            "usualresident",
            "usualresidence",
            "defactopopulation",
            "dansothuongtru",
            "danthuongtru",
            "thuongtru",
        ),
    ),
)
_CJK_TERMS: tuple[tuple[RegistrationBasis, tuple[str, ...]], ...] = (
    (RegistrationBasis.REGISTERED_HOUSEHOLD, ("戶籍", "户籍", "設籍", "设籍", "初設戶籍")),
    (RegistrationBasis.RESIDENT, ("常住", "現住", "现住", "實際居住", "实际居住")),
)

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _fold_ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALNUM.sub("", stripped.replace("đ", "d"))


def resolve_registration_basis(*texts: str) -> RegistrationBasis:
    """Resolve the population basis named by catalog text, or UNKNOWN.

    A conflict is not a tie to be broken. When the supplied text names both
    bases the metric is reported UNKNOWN, so the caveat tells the reader to
    check rather than presenting a guess as a fact.
    """

    found: set[RegistrationBasis] = set()
    for text in texts:
        if not text:
            continue
        folded = _fold_ascii(text)
        for basis, terms in _ASCII_TERMS:
            if any(term in folded for term in terms):
                found.add(basis)
        for basis, terms in _CJK_TERMS:
            if any(term in text for term in terms):
                found.add(basis)
    if len(found) != 1:
        return RegistrationBasis.UNKNOWN
    return found.pop()


_CAVEATS: dict[RegistrationBasis, str | None] = {
    RegistrationBasis.REGISTERED_HOUSEHOLD: (
        "These counts are registered household population (戶籍人口): people whose household "
        "registration is in the district, which is not necessarily where they live. Commuter "
        "and student districts can differ substantially from usual residents (常住人口)."
    ),
    RegistrationBasis.RESIDENT: (
        "These counts are usual residents (常住人口). They are not comparable with household "
        "registration counts (戶籍人口) and should not be combined with them in one rate."
    ),
    # Absence of this metadata is kept as structured state, not repeated as a
    # generic caveat on every answer. A note is only useful when the source
    # positively identifies which population definition it uses.
    RegistrationBasis.UNKNOWN: None,
}


def registration_basis_caveat(basis: RegistrationBasis) -> str | None:
    """Return a useful population-definition caveat, if the basis is known."""

    return _CAVEATS[basis]
