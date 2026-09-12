"""Local ontology: multilingual place names and demographic concept resolution."""

import pytest

from youth_compass.mapping.geography import DISTRICTS
from youth_compass.ontology import (
    DISTRICT_NAMES,
    NameLanguage,
    RegistrationBasis,
    display_name,
    district_names,
    district_spellings,
    extract_districts,
    humanize_code,
    localized_district_name,
    question_language,
    readable_entity_name,
    readable_feature_name,
    registration_basis_caveat,
    resolve_district_name,
    resolve_registration_basis,
)


def test_every_district_has_an_english_and_vietnamese_name() -> None:
    assert len(DISTRICT_NAMES) == len(DISTRICTS)
    assert {item.code for item in DISTRICT_NAMES} == {item.code for item in DISTRICTS}
    assert len({item.english for item in DISTRICT_NAMES}) == len(DISTRICT_NAMES)
    assert len({item.vietnamese for item in DISTRICT_NAMES}) == len(DISTRICT_NAMES)


@pytest.mark.parametrize(
    ("source", "code", "language"),
    [
        ("12", "12", NameLanguage.CODE),
        ("淡水區", "12", NameLanguage.ZH_HANT),
        ("新北市淡水區", "12", NameLanguage.ZH_HANT),
        ("Tamsui", "12", NameLanguage.ENGLISH),
        ("tamsui district", "12", NameLanguage.ENGLISH),
        ("Danshui", "12", NameLanguage.ENGLISH),
        ("Đạm Thủy", "12", NameLanguage.VIETNAMESE),
        ("dam thuy", "12", NameLanguage.VIETNAMESE),
        ("DAM-THUY", "12", NameLanguage.VIETNAMESE),
        ("Lâm Khẩu", "17", NameLanguage.VIETNAMESE),
        ("Linkou", "17", NameLanguage.ENGLISH),
        ("Quận Bản Kiều", "01", NameLanguage.VIETNAMESE),
    ],
)
def test_one_district_is_reached_from_every_language(
    source: str, code: str, language: NameLanguage
) -> None:
    resolution = resolve_district_name(source)
    assert resolution.resolved
    assert resolution.district is not None
    assert resolution.district.code == code
    assert resolution.language is language


@pytest.mark.parametrize("source", [None, "", "   ", "Taipei", "Kaohsiung", "site-banqiao-station"])
def test_an_unrecognized_place_is_reported_rather_than_guessed(source: object) -> None:
    resolution = resolve_district_name(source)
    assert not resolution.resolved
    assert resolution.district is None
    assert resolution.language is None


def test_spellings_expand_one_district_and_keep_the_caller_identifier_first() -> None:
    spellings = district_spellings("Đạm Thủy")
    assert spellings[0] == "Đạm Thủy"
    assert {"12", "淡水區", "Tamsui"} <= set(spellings)
    # Every spelling of one district must resolve back to that same district.
    assert {resolve_district_name(item).district for item in spellings} == {
        resolve_district_name("12").district
    }


def test_spellings_pass_an_unknown_identifier_through_untouched() -> None:
    assert district_spellings("site-banqiao-station") == ("site-banqiao-station",)
    assert district_spellings("") == ()


def test_localized_names_cover_every_language_and_reject_unknown_codes() -> None:
    assert localized_district_name("17", NameLanguage.ENGLISH) == "Linkou"
    assert localized_district_name("17", NameLanguage.VIETNAMESE) == "Lâm Khẩu"
    assert localized_district_name("17", NameLanguage.ZH_HANT) == "林口區"
    assert localized_district_name("17", NameLanguage.CODE) == "17"
    assert localized_district_name("99", NameLanguage.ENGLISH) is None
    assert district_names("99") is None


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("05_初設戶籍",), RegistrationBasis.REGISTERED_HOUSEHOLD),
        (("registered population",), RegistrationBasis.REGISTERED_HOUSEHOLD),
        (("dân số hộ khẩu",), RegistrationBasis.REGISTERED_HOUSEHOLD),
        (("常住人口",), RegistrationBasis.RESIDENT),
        (("usual residence count",), RegistrationBasis.RESIDENT),
        (("人口",), RegistrationBasis.UNKNOWN),
        ((), RegistrationBasis.UNKNOWN),
        (("", "population_count"), RegistrationBasis.UNKNOWN),
    ],
)
def test_registration_basis_is_read_from_catalog_text_only(
    texts: tuple[str, ...], expected: RegistrationBasis
) -> None:
    assert resolve_registration_basis(*texts) is expected


def test_conflicting_basis_terms_resolve_to_unknown_rather_than_a_guess() -> None:
    assert (
        resolve_registration_basis("戶籍人口", "常住人口 comparison") is RegistrationBasis.UNKNOWN
    )


def test_every_basis_carries_a_reader_facing_caveat() -> None:
    caveats = {basis: registration_basis_caveat(basis) for basis in RegistrationBasis}
    assert len(set(caveats.values())) == len(RegistrationBasis)
    assert "戶籍人口" in caveats[RegistrationBasis.UNKNOWN]
    assert "常住人口" in caveats[RegistrationBasis.UNKNOWN]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is the youth population trend in Sanxia District?", ["三峽區"]),
        ("Xu hướng dân số thanh niên ở Tam Hiệp thế nào?", ["三峽區"]),
        ("三峽區的青年人口趨勢如何？", ["三峽區"]),  # noqa: RUF001
        ("Compare Banqiao and Linkou from 2023 to 2025", ["板橋區", "林口區"]),
        ("So sánh Đạm Thủy với Lâm Khẩu", ["淡水區", "林口區"]),
        ("板橋跟淡水哪個下降比較多？", ["板橋區", "淡水區"]),  # noqa: RUF001
    ],
)
def test_districts_are_read_out_of_free_text_in_the_order_written(
    question: str, expected: list[str]
) -> None:
    assert [district.name for district in extract_districts(question)] == expected


@pytest.mark.parametrize(
    "question",
    [
        "",
        "Compare the youth population trend by district from 2023 to 2025",
        "Tôi nên mua nhà ở đâu?",
        "What is the trend in Taipei?",
    ],
)
def test_a_question_naming_no_district_yields_no_scope(question: str) -> None:
    assert extract_districts(question) == ()


def test_a_slug_entity_id_reads_as_a_name() -> None:
    assert display_name("site-linkou-center") == "Linkou Center"
    assert display_name("site_banqiao_station") == "Banqiao Station"
    assert display_name("ev-charger-01") == "EV Charger 01"


def test_a_district_identifier_is_named_in_the_requested_language() -> None:
    assert display_name("17") == "Linkou"
    assert display_name("林口區", NameLanguage.ZH_HANT) == "林口區"
    assert display_name("banqiao", NameLanguage.ZH_HANT) == "板橋區"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show me the population trend in 板橋區", NameLanguage.ENGLISH),
        ("Cho tôi xem xu hướng dân số ở 板橋區", NameLanguage.VIETNAMESE),
        ("請顯示 Banqiao 的人口趨勢", NameLanguage.ZH_HANT),
    ],
)
def test_question_language_comes_from_the_request_not_the_district_script(
    question: str, expected: NameLanguage
) -> None:
    assert question_language(question) is expected


def test_a_published_district_name_is_localized_for_the_request() -> None:
    assert readable_entity_name("01", "板橋區", NameLanguage.ENGLISH) == "Banqiao"
    assert readable_entity_name("01", "Banqiao", NameLanguage.ZH_HANT) == "板橋區"


def test_a_district_token_is_normalized_to_its_published_spelling() -> None:
    # One district must not print as two different places because a feature
    # store keyed it in a different case.
    assert display_name("site-LINKOU-center") == display_name("site-linkou-center")


def test_an_identifier_without_words_is_returned_unchanged() -> None:
    assert display_name("") == ""
    assert display_name("   ") == "   "


def test_a_snake_case_code_reads_as_a_sentence() -> None:
    assert humanize_code("ev_demand_proxy") == "EV demand proxy"
    assert humanize_code("youth_population_total") == "Youth population total"
    assert humanize_code("") == ""


def test_code_like_published_names_do_not_override_formal_labels() -> None:
    assert readable_entity_name("site-linkou-center", "site-linkou-center") == "Linkou Center"
    assert readable_entity_name("site-linkou-center", "linkou center") == "Linkou Center"
    assert readable_entity_name("venue-1", "Taipei 101") == "Taipei 101"
    assert readable_feature_name("transit_accessibility", "transit_accessibility") == (
        "Transit accessibility"
    )
