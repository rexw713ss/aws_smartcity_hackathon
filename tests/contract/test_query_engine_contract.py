"""QueryEngine contract.

Feature: aws-stage1-foundation
Properties 8 (non-allowlisted table raises), 10 (deterministic execution).
"""

import pytest

from youth_compass.domain.errors import QueryNotPermittedError
from youth_compass.ports import QueryEngine, QuerySpec

_SPEC = QuerySpec(table="fact_youth_population_monthly", metrics=["youth_population"])


class TestQueryEngineContract:
    def test_property_10_identical_spec_is_deterministic(self, query_engine: QueryEngine) -> None:
        first = query_engine.execute(_SPEC)
        second = query_engine.execute(_SPEC)
        assert first.row_count == second.row_count
        assert first.rows == second.rows
        assert first.columns == second.columns

    def test_property_8_non_allowlisted_table_raises_and_returns_no_row(
        self, query_engine: QueryEngine
    ) -> None:
        with pytest.raises(QueryNotPermittedError):
            query_engine.execute(QuerySpec(table="raw_secret", metrics=["x"]))

    def test_max_rows_is_honoured(self, query_engine: QueryEngine) -> None:
        result = query_engine.execute(
            QuerySpec(
                table="fact_youth_population_monthly", metrics=["youth_population"], max_rows=1
            )
        )
        assert result.row_count <= 1
        assert result.truncated is True
