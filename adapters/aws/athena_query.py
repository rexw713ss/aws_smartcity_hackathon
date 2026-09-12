"""Athena QueryEngine adapter with guardrails.

Feature: aws-stage2-adapters, Requirement 4.

Renders typed QuerySpec into Athena SQL entirely within the adapter. No SQL
crosses the port boundary. Enforces metric/dimension allowlists, max_rows,
query timeout, and a scanned-bytes cap.
"""

import logging
import math
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3
import botocore.exceptions

from youth_compass.domain.errors import QueryExecutionError, QueryNotPermittedError
from youth_compass.ports.query_engine import CellValue, QueryResult, QuerySpec

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60
_DEFAULT_SCAN_LIMIT = 100 * 1024 * 1024  # 100 MiB
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_INTEGER_TYPES = {"bigint", "integer", "smallint", "tinyint"}
_FLOAT_TYPES = {"double", "float", "real"}


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
        if not allowed_tables or not allowed_metrics or not allowed_dimensions:
            raise ValueError("Athena allowlists must not be empty")
        identifiers = {*allowed_tables, *allowed_metrics, *allowed_dimensions, database}
        invalid = sorted(value for value in identifiers if not _IDENTIFIER.fullmatch(value))
        if invalid:
            raise ValueError(f"invalid canonical identifiers: {invalid}")
        if timeout_seconds <= 0 or scan_limit_bytes <= 0:
            raise ValueError("Athena timeout and scan limit must be positive")
        self._database = database
        self._workgroup = workgroup
        self._output = f"s3://{output_bucket}/athena-results/"
        self._client = boto3.client("athena", region_name=region)
        self._allowed_tables = frozenset(allowed_tables)
        self._allowed_metrics = frozenset(allowed_metrics)
        self._allowed_dimensions = frozenset(allowed_dimensions)
        self._timeout = timeout_seconds
        self._scan_limit = scan_limit_bytes

    def execute(self, query: QuerySpec) -> QueryResult:
        """Render, validate, submit, poll, and return."""
        self._check_allowlist(query)
        sql = self._render_sql(query)
        try:
            return self._submit_and_poll(sql, query.max_rows)
        except botocore.exceptions.ClientError as exc:
            # The raw message names ARNs and IAM specifics that reach the API
            # client verbatim. Log it for the operator, raise only the code.
            _LOGGER.warning("athena query failed: %s", exc)
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            raise QueryExecutionError(f"the analytics engine rejected the query ({code})") from exc

    def _check_allowlist(self, query: QuerySpec) -> None:
        if query.table not in self._allowed_tables:
            raise QueryNotPermittedError(f"table {query.table!r} is not in the query allowlist")
        bad_metrics = sorted(set(query.metrics) - self._allowed_metrics)
        bad_dimensions = sorted(set(query.dimensions) - self._allowed_dimensions)
        bad_filters = sorted(set(query.filters) - self._allowed_metrics - self._allowed_dimensions)
        selected = set(query.metrics) | set(query.dimensions)
        bad_order = sorted(set(query.order_by) - selected)
        identifiers = {
            query.table,
            *query.metrics,
            *query.dimensions,
            *query.filters,
            *query.order_by,
        }
        invalid = sorted(value for value in identifiers if not _IDENTIFIER.fullmatch(value))
        if bad_metrics or bad_dimensions or bad_filters or bad_order or invalid:
            raise QueryNotPermittedError(
                "query fields are not permitted: "
                f"metrics={bad_metrics}, dimensions={bad_dimensions}, "
                f"filters={bad_filters}, order_by={bad_order}, identifiers={invalid}"
            )

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
                clauses.append(f'"{key}" = {_literal(value)}')
            sql += " WHERE " + " AND ".join(clauses)
        if query.group_by_dimensions and query.dimensions:
            sql += " GROUP BY " + ", ".join(f'"{c}"' for c in query.dimensions)
        order_by = query.order_by or (query.dimensions if query.group_by_dimensions else columns)
        sql += " ORDER BY " + ", ".join(f'"{c}"' for c in order_by)
        # Fetch one sentinel row so QueryResult.truncated is truthful.
        sql += f" LIMIT {query.max_rows + 1}"
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
                self._client.stop_query_execution(QueryExecutionId=execution_id)
                raise QueryExecutionError(f"Athena query timed out after {self._timeout}s")
            time.sleep(0.5)

        scanned = status["QueryExecution"].get("Statistics", {}).get("DataScannedInBytes", 0)
        if scanned >= self._scan_limit:
            raise QueryExecutionError(f"scanned {scanned} bytes >= limit {self._scan_limit}")

        columns: list[str] = []
        column_types: list[str] = []
        data_rows: list[list[CellValue]] = []
        token: str | None = None
        first_page = True
        while True:
            kwargs: dict[str, Any] = {"QueryExecutionId": execution_id, "MaxResults": 1000}
            if token:
                kwargs["NextToken"] = token
            results = self._client.get_query_results(**kwargs)
            info = results["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            if first_page:
                columns = [col["Name"] for col in info]
                column_types = [str(col.get("Type", "varchar")).lower() for col in info]
            raw_rows = results["ResultSet"]["Rows"]
            rows = raw_rows[1:] if first_page else raw_rows
            for row in rows:
                values = row.get("Data", [])
                data_rows.append(
                    [
                        _cell(values[index].get("VarCharValue"), column_types[index])
                        if index < len(values)
                        else None
                        for index in range(len(columns))
                    ]
                )
                if len(data_rows) > max_rows:
                    break
            if len(data_rows) > max_rows:
                break
            token = results.get("NextToken")
            if not token:
                break
            first_page = False

        truncated = len(data_rows) > max_rows
        data_rows = data_rows[:max_rows]

        return QueryResult(
            columns=columns,
            rows=data_rows,
            row_count=len(data_rows),
            scanned_bytes=scanned,
            truncated=truncated,
        )


def _literal(value: str | int | float | bool) -> str:
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and not math.isfinite(value):
        raise QueryNotPermittedError("non-finite filter values are not permitted")
    return str(value)


def _cell(value: str | None, column_type: str) -> CellValue:
    if value is None:
        return None
    try:
        if column_type in _INTEGER_TYPES:
            return int(value)
        if column_type in _FLOAT_TYPES or column_type.startswith("decimal"):
            number = Decimal(value)
            if not number.is_finite():
                raise ValueError("non-finite number")
            return float(number)
        if column_type == "boolean":
            if value.casefold() in {"true", "false"}:
                return value.casefold() == "true"
            raise ValueError("invalid boolean")
    except (InvalidOperation, ValueError) as exc:
        raise QueryExecutionError(
            f"Athena returned {value!r} for typed column {column_type!r}"
        ) from exc
    return value
