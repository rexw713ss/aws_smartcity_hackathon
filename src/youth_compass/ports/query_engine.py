"""QueryEngine port and its payload models.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.3.

The domain supplies a typed ``QuerySpec``; the adapter owns SQL rendering. This
keeps domain code free of engine-specific SQL and means no caller, including the
policy copilot, can submit arbitrary SQL.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

type FilterValue = str | int | float | bool
type CellValue = str | int | float | bool | None


class QuerySpec(BaseModel):
    """A typed, allowlist-checkable description of a read-only query."""

    table: str
    metrics: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: dict[str, FilterValue] = Field(default_factory=dict)
    order_by: list[str] = Field(default_factory=list)
    max_rows: int = Field(default=1000, ge=1, le=100_000)
    group_by_dimensions: bool = False
    """Aggregate each metric with SUM over ``dimensions`` instead of returning raw rows.

    Curated facts are stored at their source grain (age band x gender x month), so
    an entity-level question scans far more rows than it needs. Without this the
    caller must pull every row and add them up itself, which trips ``max_rows`` on
    a real dataset. SUM matches what those callers already did in application code.
    """


class QueryResult(BaseModel):
    """Rows returned by a query, with the scan cost the adapter observed."""

    columns: list[str]
    rows: list[list[CellValue]]
    row_count: int = Field(ge=0)
    scanned_bytes: int = Field(default=0, ge=0)
    truncated: bool = False


@runtime_checkable
class QueryEngine(Protocol):
    """Read-only analytical query execution against curated data."""

    def execute(self, query: QuerySpec) -> QueryResult:
        """Execute ``query`` and return its rows.

        Executing an identical ``QuerySpec`` twice against unchanged data returns
        the same row count, identical row values in identical order, and identical
        column names in identical order.

        Raises:
            QueryNotPermittedError: the spec names a table, metric, or dimension
                outside the allowlist.
            QueryExecutionError: the engine failed to execute a permitted query.
        """
        ...
