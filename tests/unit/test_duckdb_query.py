from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from adapters.local import DuckDBQueryEngine
from youth_compass.domain.errors import QueryNotPermittedError
from youth_compass.ports import QuerySpec


def _engine(tmp_path: Path) -> DuckDBQueryEngine:
    parquet = tmp_path / "facts.parquet"
    pq.write_table(
        pa.table(
            {
                "district_code": ["01", "02"],
                "metric_code": ["population_count", "population_count"],
                "metric_value": [100.0, 80.0],
            }
        ),
        parquet,
    )
    return DuckDBQueryEngine(
        tables={"population": parquet},
        allowed_metrics={"metric_value"},
        allowed_dimensions={"district_code", "metric_code"},
    )


def test_duckdb_query_filters_with_bound_parameters(tmp_path: Path) -> None:
    result = _engine(tmp_path).execute(
        QuerySpec(
            table="population",
            dimensions=["district_code"],
            metrics=["metric_value"],
            filters={"metric_code": "population_count"},
        )
    )

    assert result.rows == [["01", 100.0], ["02", 80.0]]
    assert result.scanned_bytes > 0


@pytest.mark.parametrize(
    "spec",
    [
        QuerySpec(table='population" UNION SELECT', metrics=["metric_value"]),
        QuerySpec(table="population", metrics=['metric_value" FROM secrets']),
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            filters={"secret": "x' OR 1=1 --"},
        ),
        QuerySpec(
            table="population",
            metrics=["metric_value"],
            order_by=["secret"],
        ),
    ],
)
def test_duckdb_query_rejects_non_allowlisted_fields(tmp_path: Path, spec: QuerySpec) -> None:
    with pytest.raises(QueryNotPermittedError):
        _engine(tmp_path).execute(spec)
