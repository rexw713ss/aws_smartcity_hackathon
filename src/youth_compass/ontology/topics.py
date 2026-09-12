"""Multilingual subject ontology for the published dataset topics.

`DatasetMetadata.topic` carries a canonical English slug written at ingestion
time, which is all the catalog ever stores. A question typed by a person does
not respect that: the same subject is written 人口, population, or dân số
depending on who is asking. This module is the one place that maps those
spellings onto the canonical slug, so a multi-dataset question reaches the same
executor regardless of the language it arrived in.

Matching is exact after folding (case, diacritics, separators) and is bounded to
whole words for Latin spellings. Fuzzy and substring matching are deliberately
absent for the same reason as in `districts`: guessing which subject an unknown
phrase means would silently pull the wrong table into an answer. A topic only
resolves when a curated spelling appears; nothing is inferred from broad
concepts.

The table covers the subjects present in the source archive under `data/source`,
so it stays useful as further topics are ingested.
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicNames:
    """Every spelling this system recognizes for one canonical dataset topic."""

    slug: str
    zh_hant: tuple[str, ...]
    english: tuple[str, ...]
    vietnamese: tuple[str, ...]

    @property
    def spellings(self) -> tuple[str, ...]:
        return (self.slug, *self.zh_hant, *self.english, *self.vietnamese)


# Unemployment sits under the employment topic rather than beside it: the
# catalog stores one subject per dataset, and which metric to read inside it is
# a separate decision made from the metric terms.
TOPIC_NAMES: tuple[TopicNames, ...] = (
    TopicNames(
        slug="population",
        zh_hant=("人口", "青年人口", "人口數"),
        english=("population", "residents"),
        vietnamese=("dân số", "dân cư"),
    ),
    TopicNames(
        slug="employment",
        zh_hant=("就業", "失業", "勞動力"),
        english=("employment", "unemployment", "labour force", "labor force", "jobs"),
        vietnamese=("việc làm", "thất nghiệp", "lao động"),
    ),
    TopicNames(
        slug="education",
        zh_hant=("教育程度", "教育", "學歷"),
        english=("education", "educational attainment", "schooling"),
        vietnamese=("trình độ học vấn", "học vấn", "giáo dục"),
    ),
    TopicNames(
        slug="marriage",
        zh_hant=("婚姻", "婚姻狀況"),
        english=("marriage", "marital status"),
        vietnamese=("hôn nhân", "tình trạng hôn nhân"),
    ),
    TopicNames(
        slug="migration",
        zh_hant=("遷徙", "遷入", "遷出", "人口遷移"),
        english=("migration", "inbound migration", "outbound migration"),
        vietnamese=("di cư", "nhập cư", "di dân"),
    ),
    TopicNames(
        slug="income",
        zh_hant=("所得", "收入", "平均所得"),
        english=("income", "earnings"),
        vietnamese=("thu nhập", "thu nhập bình quân"),
    ),
    TopicNames(
        slug="household_registration",
        zh_hant=("初設戶籍", "戶籍"),
        english=("household registration", "household registrations"),
        vietnamese=("hộ khẩu", "đăng ký hộ khẩu"),
    ),
    TopicNames(
        slug="birth_events",
        zh_hant=("婚育事件", "出生", "生育"),
        english=("births", "birth events", "fertility"),
        vietnamese=("sinh con", "sinh đẻ", "tỷ lệ sinh"),
    ),
)

_HAN = re.compile(r"[㐀-鿿]")
_SEPARATORS = re.compile(r"[\s\-_.,'\u2019\u00b7]+")


def _fold(value: str) -> str:
    """Case-fold and strip diacritics so "Thu Nhập" matches "thu nhap"."""

    decomposed = unicodedata.normalize("NFD", value.casefold())
    stripped = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return _SEPARATORS.sub(" ", unicodedata.normalize("NFC", stripped)).strip()


def _is_han(value: str) -> bool:
    return _HAN.search(value) is not None


def _index() -> tuple[dict[str, str], tuple[tuple[str, str], ...]]:
    """Build the exact-match index and the ordered phrase table used for search.

    Longer spellings are searched first so "教育程度" wins over "教育" and the
    more specific subject is the one that resolves.
    """

    exact: dict[str, str] = {}
    phrases: list[tuple[str, str]] = []
    for topic in TOPIC_NAMES:
        for spelling in topic.spellings:
            folded = _fold(spelling)
            if folded:
                exact.setdefault(folded, topic.slug)
                phrases.append((folded, topic.slug))
    phrases.sort(key=lambda item: (-len(item[0]), item[0]))
    return exact, tuple(phrases)


_EXACT, _PHRASES = _index()


def topic_spellings(slug: str) -> tuple[str, ...]:
    """Every recognized spelling of one canonical topic, for prompts and docs."""

    for topic in TOPIC_NAMES:
        if topic.slug == slug:
            return topic.spellings
    return ()


def resolve_topic_name(value: object) -> str | None:
    """Return the canonical topic slug for one whole name, or None."""

    if not isinstance(value, str):
        return None
    return _EXACT.get(_fold(value))


def extract_topics(question: str) -> tuple[str, ...]:
    """Return every canonical topic the question names, in first-mention order.

    Only curated spellings count. A Latin spelling must appear as whole words so
    "income" is not found inside an unrelated token; a Han spelling is matched by
    containment because written Chinese carries no word boundaries.
    """

    folded = _fold(question)
    found: dict[str, int] = {}
    for phrase, slug in _PHRASES:
        if _is_han(phrase):
            position = folded.find(phrase)
        else:
            match = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", folded)
            position = match.start() if match is not None else -1
        if position < 0:
            continue
        # A topic keeps its earliest mention, so the reading order of the
        # question decides the order of the inputs.
        if slug not in found or position < found[slug]:
            found[slug] = position
    return tuple(sorted(found, key=lambda slug: found[slug]))
