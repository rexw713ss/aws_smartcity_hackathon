"""Athena renders the same aggregation semantics as the local engine.

The moto-backed contract binding does not execute SQL, so the shared suite
cannot verify grouping there. Assert the rendered statement instead, so both
sides of the QueryEngine port stay in agreement.
"""

from unittest.mock import MagicMock, patch

import pytest

from adapters.aws.athena_query import AthenaQueryEngine
from youth_compass.domain import QueryNotPermittedError
from youth_compass.ports import QuerySpec


def _engine() -> AthenaQueryEngine:
    # Rendering is pure; the client is never called, so no AWS session is needed.
    with patch("adapters.aws.athena_query.boto3.client", return_value=MagicMock()):
        return AthenaQueryEngine(
            database="db",
            workgroup="primary",
            output_bucket="bucket",
            region="us-east-1",
            allowed_tables={"population"},
            allowed_metrics={"metric_value"},
            allowed_dimensions={"district_code"},
        )


def test_grouped_spec_renders_sum_and_group_by() -> None:
    sql = _engine()._render_sql(
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            dimensions=["district_code"],
            group_by_dimensions=True,
        )
    )
    assert 'SUM("metric_value") AS "metric_value"' in sql
    assert 'GROUP BY "district_code"' in sql


def test_default_spec_renders_no_aggregation() -> None:
    sql = _engine()._render_sql(
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            dimensions=["district_code"],
        )
    )
    assert "SUM(" not in sql
    assert "GROUP BY" not in sql
    assert 'ORDER BY "district_code", "metric_value"' in sql
    assert "LIMIT 1001" in sql


def test_string_filters_are_escaped_as_literals() -> None:
    sql = _engine()._render_sql(
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            dimensions=["district_code"],
            filters={"district_code": "x' OR 1=1 --"},
        )
    )

    assert "'x'' OR 1=1 --'" in sql


@pytest.mark.parametrize(
    "spec",
    (
        QuerySpec(table='population" UNION SELECT', metrics=["metric_value"]),
        QuerySpec(table="population", metrics=['metric_value" FROM secret']),
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            filters={"secret_column": "x"},
        ),
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            dimensions=["district_code"],
            order_by=["secret_column"],
        ),
    ),
)
def test_query_fields_fail_closed(spec: QuerySpec) -> None:
    with pytest.raises(QueryNotPermittedError):
        _engine().execute(spec)


def test_empty_allowlists_are_rejected() -> None:
    with (
        patch("adapters.aws.athena_query.boto3.client", return_value=MagicMock()),
        pytest.raises(ValueError, match="allowlists"),
    ):
        AthenaQueryEngine(
            database="db",
            workgroup="primary",
            output_bucket="bucket",
            allowed_tables=set(),
            allowed_metrics={"metric_value"},
            allowed_dimensions={"district_code"},
        )


def test_results_are_paginated_typed_and_bounded() -> None:
    engine = _engine()
    engine._client.start_query_execution.return_value = {"QueryExecutionId": "query-1"}
    engine._client.get_query_execution.return_value = {
        "QueryExecution": {
            "Status": {"State": "SUCCEEDED"},
            "Statistics": {"DataScannedInBytes": 42},
        }
    }
    info = [
        {"Name": "district_code", "Type": "varchar"},
        {"Name": "metric_value", "Type": "double"},
    ]
    engine._client.get_query_results.side_effect = [
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": info},
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "district_code"},
                            {"VarCharValue": "metric_value"},
                        ]
                    },
                    {"Data": [{"VarCharValue": "01"}, {"VarCharValue": "10.5"}]},
                ],
            },
            "NextToken": "page-2",
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": info},
                "Rows": [
                    {"Data": [{"VarCharValue": "02"}, {"VarCharValue": "11.5"}]},
                ],
            }
        },
    ]

    result = engine.execute(
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            dimensions=["district_code"],
            max_rows=1,
        )
    )

    assert result.rows == [["01", 10.5]]
    assert result.truncated is True
    assert engine._client.get_query_results.call_count == 2
