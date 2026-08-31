"""Canonical value mapping and deterministic transformations."""

from youth_compass.mapping.age import AgeRange, parse_age_range, youth_overlap
from youth_compass.mapping.engine import (
    MappingOptions,
    MappingProposalError,
    analyze_mapping,
    propose_mapping,
    validate_mapping,
)
from youth_compass.mapping.gender import normalize_gender
from youth_compass.mapping.geography import District, normalize_district
from youth_compass.mapping.time import ParsedYear, parse_year

__all__ = [
    "AgeRange",
    "District",
    "MappingOptions",
    "MappingProposalError",
    "ParsedYear",
    "analyze_mapping",
    "normalize_district",
    "normalize_gender",
    "parse_age_range",
    "parse_year",
    "propose_mapping",
    "validate_mapping",
    "youth_overlap",
]
