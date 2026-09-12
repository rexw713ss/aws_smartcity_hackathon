"""Multilingual resolution of catalog subjects."""

import pytest

from youth_compass.ontology import (
    TOPIC_NAMES,
    extract_topics,
    resolve_topic_name,
    topic_spellings,
)


@pytest.mark.parametrize(
    ("spelling", "slug"),
    [
        ("population", "population"),
        ("人口", "population"),
        ("dân số", "population"),
        ("DÂN SỐ", "population"),
        ("dan so", "population"),
        ("thất nghiệp", "employment"),
        ("失業", "employment"),
        ("教育程度", "education"),
        ("trình độ học vấn", "education"),
        ("所得", "income"),
        ("thu nhập", "income"),
    ],
)
def test_every_curated_spelling_resolves_to_its_canonical_slug(spelling: str, slug: str) -> None:
    assert resolve_topic_name(spelling) == slug


@pytest.mark.parametrize("value", ["", "unknown subject", "板橋區", None, 12])
def test_an_unlisted_value_resolves_to_nothing(value: object) -> None:
    # Guessing a subject would silently pull the wrong table into an answer.
    assert resolve_topic_name(value) is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Compare population and employment by district", ("population", "employment")),
        ("So sánh dân số và thất nghiệp theo quận", ("population", "employment")),
        ("比較各區人口與就業", ("population", "employment")),
        ("各區教育程度與所得的關係", ("education", "income")),
        ("thu nhập và trình độ học vấn theo quận", ("income", "education")),
        ("Compare population trend from 2019 to 2021", ("population",)),
        ("Where should I buy a home?", ()),
    ],
)
def test_a_question_yields_its_subjects_in_first_mention_order(
    question: str, expected: tuple[str, ...]
) -> None:
    assert extract_topics(question) == expected


def test_a_latin_spelling_is_not_found_inside_an_unrelated_word() -> None:
    # Substring matching would read "jobs" out of "jobsworth" and pull the
    # employment table into an answer that never asked for it.
    assert extract_topics("a jobsworth reviewed the population file") == ("population",)


def test_the_more_specific_chinese_subject_wins() -> None:
    # 教育程度 contains 教育; the longer spelling must decide the subject.
    assert extract_topics("教育程度") == ("education",)


def test_every_topic_exposes_its_spellings_and_they_all_resolve_back() -> None:
    for topic in TOPIC_NAMES:
        spellings = topic_spellings(topic.slug)
        assert spellings == topic.spellings
        for spelling in spellings:
            assert resolve_topic_name(spelling) == topic.slug


def test_no_spelling_is_claimed_by_two_topics() -> None:
    seen: dict[str, str] = {}
    for topic in TOPIC_NAMES:
        for spelling in topic.spellings:
            resolved = resolve_topic_name(spelling)
            assert resolved is not None
            assert seen.setdefault(spelling, resolved) == topic.slug, spelling
