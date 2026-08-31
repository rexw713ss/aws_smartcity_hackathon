import pytest

from youth_compass.mapping.geography import DISTRICTS, normalize_district


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
