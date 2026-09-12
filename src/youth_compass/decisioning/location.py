"""Canonical identity for spatial entities shared by decision use cases."""

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocationKind(StrEnum):
    """Supported spatial identity shapes without coupling to a GIS engine."""

    ADMINISTRATIVE_AREA = "administrative_area"
    GRID_CELL = "grid_cell"
    POINT = "point"
    SITE = "site"


class CanonicalLocation(BaseModel):
    """Versionable location identity used to align data from different sources."""

    model_config = ConfigDict(frozen=True)

    location_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]*$")
    kind: LocationKind
    display_name: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    spatial_reference: Literal["EPSG:4326"] = "EPSG:4326"
    h3_cell: str | None = Field(default=None, pattern=r"^[0-9a-f]+$")
    parent_location_id: str | None = None
    city_code: str | None = None
    district_code: str | None = None
    village_code: str | None = None
    aliases: tuple[str, ...] = ()
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def geometry_and_validity_must_be_consistent(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.kind in {LocationKind.POINT, LocationKind.SITE} and self.latitude is None:
            raise ValueError("point and site locations require coordinates")
        if self.kind is LocationKind.GRID_CELL and self.h3_cell is None:
            raise ValueError("grid-cell locations require an h3_cell")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from must not exceed valid_to")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("location aliases must be unique")
        return self
