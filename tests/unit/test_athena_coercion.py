"""Athena cells are coerced to the native types the QueryEngine contract returns.

Regression: the analytics layer reads year_gregorian as an int (matching the
DuckDB engine), but Athena serialises every value as a string, so the deployed
dashboard endpoints failed with 'year_gregorian is not an integer'. The adapter
coerces per column using Athena's declared types (adapters.aws.athena_query._cell).
"""

import pytest

from adapters.aws.athena_query import _cell
from youth_compass.domain.errors import QueryExecutionError


class TestCell:
    def test_integer_types_become_int(self) -> None:
        for hive_type in ("tinyint", "smallint", "integer", "bigint"):
            assert _cell("2024", hive_type) == 2024
            assert isinstance(_cell("2024", hive_type), int)

    def test_float_and_decimal_types_become_float(self) -> None:
        for hive_type in ("float", "double", "real", "decimal"):
            assert _cell("48200.0", hive_type) == 48200.0
            assert isinstance(_cell("48200.0", hive_type), float)

    def test_boolean_type_becomes_bool(self) -> None:
        assert _cell("true", "boolean") is True
        assert _cell("false", "boolean") is False

    def test_strings_stay_strings(self) -> None:
        assert _cell("板橋區", "varchar") == "板橋區"
        assert _cell("2024-01-01", "date") == "2024-01-01"

    def test_null_stays_none(self) -> None:
        assert _cell(None, "bigint") is None

    def test_an_unparseable_typed_value_raises(self) -> None:
        # A value that cannot match its declared type is a real data error.
        with pytest.raises(QueryExecutionError):
            _cell("not-a-number", "bigint")
