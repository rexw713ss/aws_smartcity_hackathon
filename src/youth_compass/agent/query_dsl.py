"""A small allowlisted aggregation language over canonical observation columns.

The agent's capability ceiling used to be hand-written: answering a new shape of
question meant adding an `if` branch and a module. This is the data-layer answer
to that. A caller — deterministic code today, a schema-constrained model
tomorrow — fills in an ``ObservationQuery``, code validates every field against
the dataset that was actually inspected, and only then is it translated into a
``QuerySpec``. Nobody writes SQL, names a table, or invents a column: the choices
are drawn from registered enums and from the metric inventory the catalog
reported.

The point is not expressiveness. It is that the same validate-then-execute
discipline the planner already applies to *tools* now applies to *queries*, so a
request for something the data cannot support is refused by construction rather
than by whichever ad-hoc check happened to be written. A metric the dataset does
not publish cannot reach the engine, and neither can a breakdown the dataset was
not published at.

Nothing here executes anything. ``translate`` returns a ``QuerySpec``, and the
``QueryEngine`` adapter remains the only thing that renders SQL.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from youth_compass.agent.contracts import DatasetInspection, GenderCode
from youth_compass.domain.canonical import CANONICAL_FIELDS
from youth_compass.domain.errors import QueryNotPermittedError
from youth_compass.ports import QuerySpec
from youth_compass.ports.query_engine import FilterValue


class Aggregation(StrEnum):
    """How repeated canonical rows are combined into one value.

    Only SUM is registered. Canonical facts sit at age-band x gender x month
    grain, so an entity-level total is a sum of disjoint parts and is always
    meaningful. An average or a maximum over those same parts is not: averaging
    age bands weights a five-year band the same as a one-year band, and a maximum
    silently answers a different question than the one asked. Adding an operation
    here requires stating which metrics it is valid for, so the enum stays a
    deliberate list rather than a passthrough for whatever SQL supports.
    """

    SUM = "sum"


class Dimension(StrEnum):
    """A breakdown an observation query may group by.

    Each member maps to canonical columns in ``_DIMENSION_COLUMNS``. The
    indirection is what keeps a caller from naming a raw column: the vocabulary
    is this enum, and the column list behind it is the application's business.
    """

    DISTRICT = "district"
    CITY = "city"
    PERIOD = "period"
    AGE_BAND = "age_band"
    GENDER = "gender"
    ESTIMATION_FLAG = "estimation_flag"


#: The canonical columns each registered dimension projects. Every name here must
#: exist in CANONICAL_FIELDS; the module asserts that on import rather than
#: letting a typo surface as an allowlist rejection at query time.
_DIMENSION_COLUMNS: dict[Dimension, tuple[str, ...]] = {
    Dimension.DISTRICT: ("district_code", "district_name"),
    Dimension.CITY: ("city_code", "city_name"),
    Dimension.PERIOD: ("year_gregorian", "month"),
    Dimension.AGE_BAND: ("age_lower", "age_upper"),
    Dimension.GENDER: ("gender_code",),
    Dimension.ESTIMATION_FLAG: ("is_estimated",),
}

#: Columns every observation query returns regardless of breakdown, because the
#: application cannot interpret a value without them. A unit or population scope
#: that varies inside one result makes the numbers incomparable, and the caller
#: has to be able to see that rather than average over it.
_ALWAYS_PROJECTED: tuple[str, ...] = (
    "metric_code",
    "unit_code",
    "population_scope",
)

_MEASURE = "metric_value"

_UNKNOWN = sorted(
    {
        column
        for columns in _DIMENSION_COLUMNS.values()
        for column in columns
        if column not in CANONICAL_FIELDS
    }
    | {column for column in (*_ALWAYS_PROJECTED, _MEASURE) if column not in CANONICAL_FIELDS}
)
if _UNKNOWN:  # pragma: no cover - a build-time contradiction, not a runtime path
    raise ImportError(f"query DSL names non-canonical columns: {_UNKNOWN}")


class ObservationQuery(BaseModel):
    """One bounded aggregation request over a single published dataset version.

    ``extra="forbid"`` matters more here than elsewhere: this is the shape a model
    is asked to fill, and an unrecognized field is a sign the caller believes it
    can ask for something the language does not offer. Failing loudly is better
    than silently dropping it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    aggregation: Aggregation = Aggregation.SUM
    group_by: tuple[Dimension, ...] = (Dimension.DISTRICT, Dimension.PERIOD)
    entity_ids: tuple[str, ...] = ()
    year_from: int | None = Field(default=None, ge=1900, le=2200)
    year_to: int | None = Field(default=None, ge=1900, le=2200)
    age_lower: int | None = Field(default=None, ge=0, le=120)
    age_upper: int | None = Field(default=None, ge=0, le=120)
    gender_code: GenderCode | None = None
    max_rows: int = Field(default=100_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "ObservationQuery":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not exceed year_to")
        if (
            self.age_lower is not None
            and self.age_upper is not None
            and self.age_lower > self.age_upper
        ):
            raise ValueError("age_lower must not exceed age_upper")
        if not self.group_by:
            raise ValueError("an observation query must group by at least one dimension")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by must not repeat a dimension")
        return self


def validate(query: ObservationQuery, inspection: DatasetInspection) -> ObservationQuery:
    """Check a query against the dataset that was actually inspected.

    Two things are enforced that a schema cannot express, because both depend on
    the dataset in hand rather than on the shape of the request:

    A metric the dataset does not publish is refused. This is the structural form
    of a bug that used to be reachable — a question about unemployment answered
    with population counts, because whichever metric existed was selected once
    the candidate list had only one entry.

    A breakdown the dataset was not published at is refused too. Grouping by
    gender in a table that carries no gender column does not produce an error
    from the engine; it produces one row per entity labelled as though gender had
    been considered, which is a quieter kind of wrong.
    """

    if query.metric_code not in inspection.available_metrics:
        raise QueryNotPermittedError(
            f"dataset {inspection.dataset_id!r} does not publish metric "
            f"{query.metric_code!r}; available: {', '.join(inspection.available_metrics)}"
        )
    grain = set(inspection.grain)
    unsupported = sorted(
        dimension.value
        for dimension in query.group_by
        if _GRAIN_REQUIREMENT.get(dimension) is not None
        and not (_GRAIN_REQUIREMENT[dimension] or set()) & grain
    )
    if unsupported:
        raise QueryNotPermittedError(
            f"dataset {inspection.dataset_id!r} is not published by "
            f"{', '.join(unsupported)}; its grain is {', '.join(sorted(grain))}"
        )
    return query


#: Which declared grain dimensions justify a breakdown. A dataset states its grain
#: in catalog metadata; a breakdown is only honest if the grain mentions it.
#: PERIOD and the estimation flag are deliberately absent: every canonical row
#: carries a period and an is_estimated column, so those never need justifying.
_GRAIN_REQUIREMENT: dict[Dimension, set[str] | None] = {
    Dimension.DISTRICT: {"district", "district_code", "geography"},
    Dimension.CITY: {"city", "city_code", "geography"},
    Dimension.AGE_BAND: {"age", "age_band", "age_label", "age_lower"},
    Dimension.GENDER: {"gender", "gender_code"},
    Dimension.PERIOD: None,
    Dimension.ESTIMATION_FLAG: None,
}


def translate(query: ObservationQuery, inspection: DatasetInspection) -> QuerySpec:
    """Turn a validated query into the typed spec the engine allowlist accepts.

    Filters that the engine can apply are pushed down; filters that need
    row-level interpretation the engine has no vocabulary for — an age band
    contained inside a requested range, a district named in another language —
    stay with the caller. Pushing what can be pushed is what keeps a real dataset
    inside the row guard: adding gender to the grouping multiplies the returned
    rows, while filtering it away before grouping does not.
    """

    dimensions: list[str] = []
    for dimension in query.group_by:
        for column in _DIMENSION_COLUMNS[dimension]:
            if column not in dimensions:
                dimensions.append(column)
    for column in _ALWAYS_PROJECTED:
        if column not in dimensions:
            dimensions.append(column)

    filters: dict[str, FilterValue] = {"metric_code": query.metric_code}
    if query.gender_code is not None:
        filters["gender_code"] = query.gender_code

    return QuerySpec(
        table=inspection.dataset_id,
        dimensions=dimensions,
        metrics=[_MEASURE],
        filters=filters,
        # Curated facts sit below the requested breakdown, so aggregate in the
        # engine instead of scanning every source row into memory. SUM is the only
        # registered aggregation, which is why this is a flag rather than a name.
        group_by_dimensions=query.aggregation is Aggregation.SUM,
        max_rows=query.max_rows,
    )


__all__ = [
    "Aggregation",
    "Dimension",
    "ObservationQuery",
    "translate",
    "validate",
]
