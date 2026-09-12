"""Deterministic location resolution for canonical New Taipei districts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.decisioning.location import CanonicalLocation, LocationKind
from youth_compass.mapping.geography import DISTRICTS, normalize_district


class LocationResolutionMethod(StrEnum):
    """Auditable method by which a source location became canonical."""

    EXACT_ID = "exact_id"
    DISTRICT_ALIAS = "district_alias"
    UNRESOLVED = "unresolved"


class LocationResolution(BaseModel):
    """Result of resolving one source geography value."""

    model_config = ConfigDict(frozen=True)

    source_value: str
    location: CanonicalLocation | None
    method: LocationResolutionMethod
    confidence: float = Field(ge=0.0, le=1.0)


class NewTaipeiDistrictResolver:
    """Resolve current district identifiers and common aliases without a network call."""

    def __init__(self) -> None:
        locations = (_district_location(item.code, item.name) for item in DISTRICTS)
        self._locations = {location.location_id: location for location in locations}

    def resolve(self, source_value: object) -> LocationResolution:
        raw = "" if source_value is None else str(source_value).strip()
        if raw in self._locations:
            return LocationResolution(
                source_value=raw,
                location=self._locations[raw],
                method=LocationResolutionMethod.EXACT_ID,
                confidence=1.0,
            )
        district = normalize_district(source_value)
        if district is None:
            return LocationResolution(
                source_value=raw,
                location=None,
                method=LocationResolutionMethod.UNRESOLVED,
                confidence=0.0,
            )
        return LocationResolution(
            source_value=raw,
            location=self._locations[_district_location_id(district.code)],
            method=LocationResolutionMethod.DISTRICT_ALIAS,
            confidence=1.0,
        )

    def list_locations(self) -> tuple[CanonicalLocation, ...]:
        return tuple(self._locations[key] for key in sorted(self._locations))


def _district_location(code: str, name: str) -> CanonicalLocation:
    short_name = name.removesuffix("區")
    aliases = tuple(dict.fromkeys((code, str(int(code)), short_name, name, f"新北市{name}")))
    return CanonicalLocation(
        location_id=_district_location_id(code),
        kind=LocationKind.ADMINISTRATIVE_AREA,
        display_name=name,
        parent_location_id="city:65000",
        city_code="65000",
        district_code=code,
        aliases=aliases,
    )


def _district_location_id(code: str) -> str:
    return f"district:65000:{code}"
