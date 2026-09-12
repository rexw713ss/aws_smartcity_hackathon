"""Athena renders the same aggregation semantics as the local engine.

The moto-backed contract binding does not execute SQL, so the shared suite
cannot verify grouping there. Assert the rendered statement instead, so both
sides of the QueryEngine port stay in agreement.
"""

from unittest.mock import MagicMock, patch

from adapters.aws.athena_query import AthenaQueryEngine
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
