"""The generated frontend district dictionary must track the backend."""

import json
from pathlib import Path

from scripts.generate_district_dictionary import _ATLAS, _OUTPUT, build
from youth_compass.mapping.geography import DISTRICTS


def test_generated_dictionary_is_current() -> None:
    """Regenerate with `uv run python -m scripts.generate_district_dictionary`."""

    assert _OUTPUT.read_text(encoding="utf-8") == build()


def test_atlas_number_is_not_the_backend_code() -> None:
    """Guard the trap the generator exists to avoid.

    The atlas numbers districts alphabetically by English name, so joining on
    `number` would map backend code '02' (三重區) onto atlas 2 (板橋區). The
    dictionary must therefore never be built from that field.
    """

    atlas = json.loads(Path(_ATLAS).read_text(encoding="utf-8"))
    by_number = {int(area["number"]): area["name"] for area in atlas["districts"]}
    mismatches = [
        district.name
        for district in DISTRICTS
        if by_number.get(int(district.code)) != district.name
    ]
    assert mismatches, "atlas numbering now matches the backend codes; revisit the join"
    # The specific collision the comment in districts.ts calls out.
    assert by_number[2] == "板橋區"
    assert next(d.name for d in DISTRICTS if d.code == "02") == "三重區"


def test_every_backend_district_has_a_map_area() -> None:
    atlas = json.loads(Path(_ATLAS).read_text(encoding="utf-8"))
    names = {area["name"] for area in atlas["districts"]}
    assert {district.name for district in DISTRICTS} == names
