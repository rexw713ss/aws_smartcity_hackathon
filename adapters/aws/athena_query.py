"""Athena QueryEngine adapter with guardrails.

Feature: aws-stage2-adapters, Requirement 4.

Renders typed QuerySpec into Athena SQL entirely within the adapter. No SQL
crosses the port boundary. Enforces metric/dimension allowlists, max_rows,
query timeout, and a scanned-bytes cap.
"""

import time

import boto3
import botocore.exceptions

from youth_compass.domain.errors import QueryExecutionError, QueryNotPermittedError
from youth_compass.ports.query_engine import CellValue, QueryResult, QuerySpec

_DEFAULT_TIMEOUT_S = 60
_DEFAULT_SCAN_LIMIT = 100 * 1024 * 1024  # 100 MiB

# Athena/Hive scalar type names -> the CellValue kind to coerce to. Athena
# reports these in each column's ResultSetMetadata; anything not listed
# (varchar, date, timestamp, …) stays a string.
_INTEGER_TYPES = frozenset({"tinyint", "smallint", "integer", "int", "bigint"})
_FLOAT_TYPES = frozenset({"float", "double", "real", "decimal"})


def _coerce(value: str | None, column_type: str) -> CellValue:
    """Turn an Athena string cell into the native type its column declares.

    Athena serialises every value as a string; the QueryEngine contract returns
    native types, so consumers (the analytics layer) can treat DuckDB and Athena
    identically. A value that does not parse is left as the original string
    rather than raising, so one malformed cell cannot fail a whole query.
    """
    if value is None:
        return None
    kind = column_type.split("(", 1)[0].strip().lower()
    if kind in _INTEGER_TYPES:
        try:
            return int(value)
        except ValueError:
            return value
    if kind in _FLOAT_TYPES:
        try:
            return float(value)
        except ValueError:
            return value
    if kind == "boolean":
        if value in ("true", "false"):
            return value == "true"
        return value
    return value


class AthenaQueryEngine:
    """QueryEngine backed by Amazon Athena."""

    def __init__(
        self,
        database: str,
        workgroup: str,
        output_bucket: str,
        region: str = "us-east-1",
        *,
        allowed_tables: set[str] | None = None,
        allowed_metrics: set[str] | None = None,
        allowed_dimensions: set[str] | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_S,
        scan_limit_bytes: int = _DEFAULT_SCAN_LIMIT,
    ) -> None:
        self._database = database
        self._workgroup = workgroup
        self._output = f"s3://{output_bucket}/athena-results/"
        self._client = boto3.client("athena", region_name=region)
        self._allowed_tables = allowed_tables or set()
        self._allowed_metrics = allowed_metrics or set()
        self._allowed_dimensions = allowed_dimensions or set()
        self._timeout = timeout_seconds
        self._scan_limit = scan_limit_bytes

    def execute(self, query: QuerySpec) -> QueryResult:
        """Render, validate, submit, poll, and return."""
        self._check_allowlist(query)
        sql = self._render_sql(query)
        try:
            return self._submit_and_poll(sql, query.max_rows)
        except botocore.exceptions.ClientError as exc:
            raise QueryExecutionError(str(exc)[:200]) from exc

    def _check_allowlist(self, query: QuerySpec) -> None:
        if self._allowed_tables and query.table not in self._allowed_tables:
            raise QueryNotPermittedError(f"table {query.table!r} is not in the query allowlist")
        if self._allowed_metrics:
            bad = [m for m in query.metrics if m not in self._allowed_metrics]
            if bad:
                raise QueryNotPermittedError(f"metrics not allowed: {bad}")
        if self._allowed_dimensions:
            bad = [d for d in query.dimensions if d not in self._allowed_dimensions]
            if bad:
                raise QueryNotPermittedError(f"dimensions not allowed: {bad}")

    def _render_sql(self, query: QuerySpec) -> str:
        columns = [*query.dimensions, *query.metrics]
        if query.group_by_dimensions:
            projected = [
                *(f'"{c}"' for c in query.dimensions),
                *(f'SUM("{m}") AS "{m}"' for m in query.metrics),
            ]
        else:
            projected = [f'"{c}"' for c in columns]
        select = ", ".join(projected)
        sql = f'SELECT {select} FROM "{self._database}"."{query.table}"'
        if query.filters:
            clauses = []
            for key, value in query.filters.items():
                if isinstance(value, str):
                    clauses.append(f"\"{key}\" = '{value}'")
                else:
                    clauses.append(f'"{key}" = {value}')
            sql += " WHERE " + " AND ".join(clauses)
        if query.group_by_dimensions and query.dimensions:
            sql += " GROUP BY " + ", ".join(f'"{c}"' for c in query.dimensions)
        if query.order_by:
            sql += " ORDER BY " + ", ".join(f'"{c}"' for c in query.order_by)
        sql += f" LIMIT {query.max_rows}"
        return sql

    def _submit_and_poll(self, sql: str, max_rows: int) -> QueryResult:
        response = self._client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": self._database},
            WorkGroup=self._workgroup,
            ResultConfiguration={"OutputLocation": self._output},
        )
        execution_id = response["QueryExecutionId"]
        deadline = time.monotonic() + self._timeout
        while True:
            status = self._client.get_query_execution(QueryExecutionId=execution_id)
            state = status["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            if state in ("FAILED", "CANCELLED"):
                reason = status["QueryExecution"]["Status"].get("StateChangeReason", state)
                raise QueryExecutionError(f"Athena query {state}: {reason}"[:200])
            if time.monotonic() > deadline:
                raise QueryExecutionError(f"Athena query timed out after {self._timeout}s")
            time.sleep(0.5)

        scanned = status["QueryExecution"].get("Statistics", {}).get("DataScannedInBytes", 0)
        if scanned >= self._scan_limit:
            raise QueryExecutionError(f"scanned {scanned} bytes >= limit {self._scan_limit}")

        results = self._client.get_query_results(QueryExecutionId=execution_id)
        column_info = results["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
        columns: list[str] = [col["Name"] for col in column_info]
        # Athena returns every cell as a string; the QueryEngine contract (and
        # the analytics layer that consumes it) expects native types, matching
        # the DuckDB engine. Coerce per column using Athena's declared types.
        column_types: list[str] = [str(col.get("Type", "varchar")) for col in column_info]
        raw_rows = results["ResultSet"]["Rows"]
        # First row is the header in Athena results; skip it.
        data_rows: list[list[CellValue]] = []
        for row in raw_rows[1 : max_rows + 1]:
            data_rows.append(
                [
                    _coerce(datum.get("VarCharValue"), column_types[index])
                    for index, datum in enumerate(row["Data"])
                ]
            )

        return QueryResult(
            columns=columns,
            rows=data_rows,
            row_count=len(data_rows),
            scanned_bytes=scanned,
            truncated=len(raw_rows) - 1 > max_rows,
        )
