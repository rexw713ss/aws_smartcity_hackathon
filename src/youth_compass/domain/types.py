"""Enums shared by profiling and canonical mapping."""

from enum import StrEnum


class FileFormat(StrEnum):
    CSV = "csv"


class PrimitiveType(StrEnum):
    EMPTY = "empty"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    DATE = "date"
    STRING = "string"


class SemanticRole(StrEnum):
    YEAR = "year"
    MONTH = "month"
    DISTRICT_CODE = "district_code"
    DISTRICT_NAME = "district_name"
    AGE_LABEL = "age_label"
    AGE_LOWER = "age_lower"
    AGE_UPPER = "age_upper"
    GENDER = "gender"
    METRIC = "metric"
    DIMENSION = "dimension"
    UNKNOWN = "unknown"


class WarningSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
