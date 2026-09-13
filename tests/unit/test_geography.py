import pytest

from youth_compass.mapping.geography import DISTRICTS, extract_district, normalize_district


def test_dictionary_contains_all_new_taipei_districts() -> None:
    assert len(DISTRICTS) == 29
    assert len({district.code for district in DISTRICTS}) == 29
    assert len({district.name for district in DISTRICTS}) == 29


@pytest.mark.parametrize(
    ("source", "code", "name"),
    [
        ("板橋", "01", "板橋區"),
        ("板橋區", "01", "板橋區"),
        ("新北市板橋區", "01", "板橋區"),
        ("  新北市 林口區 ", "17", "林口區"),
        ("1", "01", "板橋區"),
        ("1.0", "01", "板橋區"),
        (1.0, "01", "板橋區"),
        (23, "23", "石門區"),
    ],
)
def test_normalize_district(source: object, code: str, name: str) -> None:
    district = normalize_district(source)
    assert district is not None
    assert district.code == code
    assert district.name == name


@pytest.mark.parametrize("source", [None, "", "Unknown", "臺北市中正區", "99"])
def test_unknown_district_returns_none(source: object) -> None:
    assert normalize_district(source) is None


def test_extract_district_from_new_taipei_building_site() -> None:
    district = extract_district("新北市林口區新林段216-2地號")

    assert district is not None
    assert district.code == "17"


def test_extract_district_from_site_without_city_prefix() -> None:
    district = extract_district("淡水區新市段107地號")

    assert district is not None
    assert district.code == "12"


def test_extract_district_refuses_an_address_outside_new_taipei() -> None:
    assert extract_district("臺北市中正區忠孝東路") is None
    assert extract_district("臺北市板橋區文化路") is None
