"""Allowlisted deterministic transformations available to mapping proposals."""

from dataclasses import dataclass

from youth_compass.domain.types import PrimitiveType


@dataclass(frozen=True, slots=True)
class TransformationDefinition:
    name: str
    accepted_types: frozenset[PrimitiveType]
    description: str


def _types(*values: PrimitiveType) -> frozenset[PrimitiveType]:
    return frozenset(values)


TRANSFORMATIONS = {
    definition.name: definition
    for definition in (
        TransformationDefinition(
            "parse_year",
            _types(PrimitiveType.INTEGER, PrimitiveType.STRING),
            "Parse ROC or Gregorian year and emit normalized calendar fields.",
        ),
        TransformationDefinition(
            "parse_compact_date",
            _types(PrimitiveType.INTEGER, PrimitiveType.STRING),
            "Parse ROC YYYMMDD or Gregorian YYYYMMDD and emit calendar fields.",
        ),
        TransformationDefinition(
            "parse_month",
            _types(PrimitiveType.INTEGER, PrimitiveType.STRING, PrimitiveType.EMPTY),
            "Parse month values from 1 through 12.",
        ),
        TransformationDefinition(
            "normalize_district_code",
            _types(PrimitiveType.INTEGER, PrimitiveType.FLOAT, PrimitiveType.STRING),
            "Resolve a New Taipei district code.",
        ),
        TransformationDefinition(
            "normalize_district",
            _types(PrimitiveType.STRING),
            "Resolve district aliases to canonical code and name.",
        ),
        TransformationDefinition(
            "extract_district",
            _types(PrimitiveType.STRING),
            "Extract one explicit New Taipei district from an address or building site.",
        ),
        TransformationDefinition(
            "parse_age_range",
            _types(PrimitiveType.INTEGER, PrimitiveType.STRING),
            "Parse age bounds and derive youth overlap fields.",
        ),
        TransformationDefinition(
            "parse_integer",
            _types(PrimitiveType.INTEGER, PrimitiveType.FLOAT, PrimitiveType.STRING),
            "Parse an integer value.",
        ),
        TransformationDefinition(
            "parse_float",
            _types(PrimitiveType.INTEGER, PrimitiveType.FLOAT, PrimitiveType.STRING),
            "Parse a finite floating-point value.",
        ),
        TransformationDefinition(
            "normalize_gender",
            _types(PrimitiveType.STRING),
            "Normalize known gender aliases.",
        ),
        TransformationDefinition(
            "normalize_education",
            _types(PrimitiveType.STRING),
            "Normalize education labels using the canonical dictionary.",
        ),
        TransformationDefinition(
            "normalize_graduation_status",
            _types(PrimitiveType.STRING),
            "Normalize graduation status labels.",
        ),
        TransformationDefinition(
            "normalize_marital_status",
            _types(PrimitiveType.STRING),
            "Normalize marital status labels.",
        ),
        TransformationDefinition(
            "normalize_boolean",
            _types(PrimitiveType.BOOLEAN, PrimitiveType.INTEGER, PrimitiveType.STRING),
            "Normalize a boolean-compatible source value.",
        ),
        TransformationDefinition(
            "normalize_direction",
            _types(PrimitiveType.STRING),
            "Normalize migration direction.",
        ),
        TransformationDefinition(
            "normalize_event",
            _types(PrimitiveType.STRING),
            "Normalize event labels.",
        ),
        TransformationDefinition(
            "normalize_marriage_type",
            _types(PrimitiveType.STRING),
            "Normalize marriage type labels.",
        ),
        TransformationDefinition(
            "normalize_youth_relationship",
            _types(PrimitiveType.STRING),
            "Normalize existing youth relationship labels.",
        ),
        TransformationDefinition(
            "normalize_text",
            _types(PrimitiveType.STRING),
            "Trim and normalize text without changing semantics.",
        ),
    )
}


def get_transformation(name: str) -> TransformationDefinition | None:
    return TRANSFORMATIONS.get(name)
