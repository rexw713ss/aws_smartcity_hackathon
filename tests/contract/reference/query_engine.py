"""In-memory QueryEngine reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager

from tests.contract.registry import register_query_engine
from youth_compass.domain.errors import QueryExecutionError, QueryNotPermittedError
from youth_compass.ports import QueryEngine, QueryResult, QuerySpec

# A tiny fixed dataset so identical specs return identical, ordered rows.
_ALLOWLISTED_TABLES = {
    "fact_youth_population_monthly": {
        "columns": ["district_code", "youth_population"],
        "rows": [
            ["01", 1200],
            ["02", 3400],
            ["03", 2980],
        ],
    }
}


class InMemoryQueryEngine:
    """Allowlist-aware, deterministic in row and column order, honours max_rows."""

    def execute(self, query: QuerySpec) -> QueryResult:
        table = _ALLOWLISTED_TABLES.get(query.table)
        if table is None:
            raise QueryNotPermittedError(f"table {query.table!r} is not in the query allowlist")
        requested = ["district_code", *query.metrics]
        available = set(table["columns"])
        missing = [c for c in query.metrics if c not in available]
        if missing:
            raise QueryExecutionError(f"unknown metrics: {', '.join(missing)}")
        index = {name: i for i, name in enumerate(table["columns"])}
        rows = [[row[index[c]] for c in requested] for row in table["rows"]]
        if query.group_by_dimensions:
            grouped: dict[object, list[object]] = {}
            for row in rows:
                key = row[0]
                existing = grouped.get(key)
                if existing is None:
                    grouped[key] = list(row)
                    continue
                for position in range(1, len(row)):
                    existing[position] += row[position]
            rows = [grouped[key] for key in sorted(grouped)]
        truncated = len(rows) > query.max_rows
        rows = rows[: query.max_rows]
        return QueryResult(
            columns=requested,
            rows=rows,
            row_count=len(rows),
            scanned_bytes=0,
            truncated=truncated,
        )


@register_query_engine("reference")
@contextmanager
def _reference_query_engine() -> Iterator[QueryEngine]:
    yield InMemoryQueryEngine()
