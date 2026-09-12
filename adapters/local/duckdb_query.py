"""Allowlisted DuckDB QueryEngine over trusted curated Parquet files."""

import re
from pathlib import Path

import duckdb

from youth_compass.domain.errors import QueryExecutionError, QueryNotPermittedError
from youth_compass.ports import QueryResult, QuerySpec
from youth_compass.ports.query_engine import CellValue

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class DuckDBQueryEngine:
    """Render typed read-only queries; callers never supply SQL fragments."""

    def __init__(
        self,
        *,
        tables: dict[str, Path],
        allowed_metrics: set[str],
        allowed_dimensions: set[str],
    ) -> None:
        if not tables or not allowed_metrics:
            raise ValueError("DuckDB allowlists must not be empty")
        identifiers = {*tables, *allowed_metrics, *allowed_dimensions}
        invalid = sorted(value for value in identifiers if not _IDENTIFIER.fullmatch(value))
        if invalid:
            raise ValueError(f"invalid canonical identifiers: {invalid}")
        self._tables = {name: path.resolve() for name, path in tables.items()}
        self._metrics = frozenset(allowed_metrics)
        self._dimensions = frozenset(allowed_dimensions)

    def execute(self, query: QuerySpec) -> QueryResult:
        path = self._validate(query)
        columns = [*query.dimensions, *query.metrics]
        select = ", ".join(_quote(column) for column in columns)
        clauses: list[str] = []
        parameters: list[object] = [str(path)]
        for key, value in query.filters.items():
            clauses.append(f"{_quote(key)} = ?")
            parameters.append(value)
        sql = f"SELECT {select} FROM read_parquet(?)"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        order_by = query.order_by or columns
        sql += " ORDER BY " + ", ".join(_quote(column) for column in order_by)
        sql += " LIMIT ?"
        parameters.append(query.max_rows + 1)

        connection = duckdb.connect(database=":memory:")
        try:
            raw_rows = connection.execute(sql, parameters).fetchall()
        except duckdb.Error as exc:
            raise QueryExecutionError(f"DuckDB query failed: {str(exc)[:300]}") from exc
        finally:
            connection.close()
        truncated = len(raw_rows) > query.max_rows
        rows = raw_rows[: query.max_rows]
        return QueryResult(
            columns=columns,
            rows=[[_cell(value) for value in row] for row in rows],
            row_count=len(rows),
            scanned_bytes=path.stat().st_size,
            truncated=truncated,
        )

    def _validate(self, query: QuerySpec) -> Path:
        path = self._tables.get(query.table)
        if path is None:
            raise QueryNotPermittedError(f"table {query.table!r} is not allowlisted")
        if not path.is_file():
            raise QueryExecutionError(f"curated table {query.table!r} is unavailable")
        bad_metrics = sorted(set(query.metrics) - self._metrics)
        bad_dimensions = sorted(set(query.dimensions) - self._dimensions)
        bad_filters = sorted(set(query.filters) - self._metrics - self._dimensions)
        selected = set(query.metrics) | set(query.dimensions)
        bad_order = sorted(set(query.order_by) - selected)
        if bad_metrics or bad_dimensions or bad_filters or bad_order:
            raise QueryNotPermittedError(
                "query fields are not permitted: "
                f"metrics={bad_metrics}, dimensions={bad_dimensions}, "
                f"filters={bad_filters}, order_by={bad_order}"
            )
        return path


def _quote(identifier: str) -> str:
    return f'"{identifier}"'


def _cell(value: object) -> CellValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
