"""DuckDB QueryEngine binding for the shared contract suite."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from adapters.local import DuckDBQueryEngine
from tests.contract.registry import register_query_engine
from youth_compass.ports import QueryEngine


@register_query_engine("duckdb")
@contextmanager
def _duckdb_query() -> Iterator[QueryEngine]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "population.parquet"
        pq.write_table(
            pa.table(
                {
                    "district_code": ["01", "02", "03"],
                    "youth_population": [1200.0, 3400.0, 2980.0],
                }
            ),
            path,
        )
        yield DuckDBQueryEngine(
            tables={"fact_youth_population_monthly": path},
            allowed_metrics={"youth_population"},
            allowed_dimensions={"district_code"},
        )
