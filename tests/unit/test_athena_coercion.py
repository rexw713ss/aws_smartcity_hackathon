"""Athena cells are coerced to the native types the QueryEngine contract returns.

Regression: the analytics layer reads year_gregorian as an int (matching the
DuckDB engine), but Athena serialises every value as a string, so the deployed
dashboard endpoints failed with 'year_gregorian is not an integer'. The adapter
now coerces per column using Athena's declared types.
"""

from adapters.aws.athena_query import _coerce


class TestCoerce:
    def test_integer_types_become_int(self) -> None:
        for hive_type in ("tinyint", "smallint", "integer", "int", "bigint"):
            assert _coerce("2024", hive_type) == 2024
            assert isinstance(_coerce("2024", hive_type), int)

    def test_float_types_become_float(self) -> None:
        for hive_type in ("float", "double", "real", "decimal(10,2)"):
            assert _coerce("48200.0", hive_type) == 48200.0
            assert isinstance(_coerce("48200.0", hive_type), float)

    def test_boolean_type_becomes_bool(self) -> None:
        assert _coerce("true", "boolean") is True
        assert _coerce("false", "boolean") is False

    def test_strings_stay_strings(self) -> None:
        assert _coerce("板橋區", "varchar") == "板橋區"
        assert _coerce("2024-01-01", "date") == "2024-01-01"

    def test_null_stays_none(self) -> None:
        assert _coerce(None, "bigint") is None

    def test_an_unparseable_value_is_left_as_a_string(self) -> None:
        # One malformed cell must not fail the whole query.
        assert _coerce("not-a-number", "bigint") == "not-a-number"
