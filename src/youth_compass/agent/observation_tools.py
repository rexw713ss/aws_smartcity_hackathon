"""Bounded tools for inspecting, querying, and comparing canonical observations."""

import re
from collections.abc import Callable
from typing import Protocol

from youth_compass.agent.contracts import (
    DatasetInspection,
    DecomposedQuery,
    EntityChange,
    EntityComparison,
    ObservationPoint,
    ObservationSeries,
)
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import QueryExecutionError
from youth_compass.ontology import resolve_district_name
from youth_compass.ports import QueryEngine, QuerySpec
from youth_compass.ports.query_engine import CellValue, FilterValue

_INSPECTION_DIMENSIONS = [
    "year_gregorian",
    "month",
    "city_code",
    "city_name",
    "district_code",
    "district_name",
    "metric_code",
    "unit_code",
    "population_scope",
    "is_estimated",
]
# Added to the projection only when a filter needs them, so an unfiltered
# query keeps the narrower grain it already scanned.
_AGE_DIMENSIONS = ["age_lower", "age_upper"]
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_LAST_YEARS = re.compile(
    r"(?:last|past|trong)\s+(\d+)\s+(?:years?|năm)|\b(\d+)\s+năm\s+(?:qua|gần đây)"
    r"|(?:過去|最近)\s*(\d+)\s*年"
)


class DatasetCatalogReader(Protocol):
    """Read-only catalog surface needed by the inspection tool."""

    def list_datasets(self) -> list[DatasetMetadata]:
        """Return visible dataset records."""
        ...

    def get(self, dataset_id: str) -> DatasetMetadata:
        """Return the visible version for one dataset."""
        ...


type QueryEngineFactory = Callable[[DatasetMetadata], QueryEngine]


class InspectDatasetTool:
    """Select one relevant published dataset and verify its actual coverage."""

    def __init__(
        self, catalog: DatasetCatalogReader, query_engine_factory: QueryEngineFactory
    ) -> None:
        self._catalog = catalog
        self._query_engine_factory = query_engine_factory

    def execute(
        self, decomposition: DecomposedQuery, *, min_quality_score: float = 0.0
    ) -> DatasetInspection:
        candidates = [
            item
            for item in self._catalog.list_datasets()
            if item.status is DatasetStatus.PUBLISHED and item.quality_score >= min_quality_score
        ]
        metadata = _select_dataset(candidates, decomposition)
        return self._inspect(metadata, decomposition)

    def execute_for_dataset(
        self,
        decomposition: DecomposedQuery,
        dataset_id: str,
        *,
        min_quality_score: float = 0.0,
    ) -> DatasetInspection:
        """Inspect one explicitly requested immutable published dataset."""

        metadata = self._catalog.get(dataset_id)
        if (
            metadata.status is not DatasetStatus.PUBLISHED
            or metadata.quality_score < min_quality_score
        ):
            raise QueryExecutionError(
                f"dataset {dataset_id!r} is not published at the requested quality"
            )
        return self._inspect(metadata, decomposition)

    def _inspect(
        self, metadata: DatasetMetadata, decomposition: DecomposedQuery
    ) -> DatasetInspection:
        result = self._query_engine_factory(metadata).execute(
            QuerySpec(
                table=metadata.dataset_id,
                dimensions=_INSPECTION_DIMENSIONS,
                metrics=["metric_value"],
                # Curated facts sit at age-band x gender grain; inspection only needs
                # the distinct coverage, so group in the engine rather than scanning
                # every source row into memory and tripping the row guard.
                group_by_dimensions=True,
                max_rows=100_000,
            )
        )
        if result.truncated:
            raise QueryExecutionError("dataset inspection exceeded the safe 100000-row query limit")
        records = _records(result.columns, result.rows)
        if not records:
            raise QueryExecutionError("the selected published dataset has no observations")
        available_metrics = tuple(sorted({str(row["metric_code"]) for row in records}))
        metric_code = _select_metric(available_metrics, decomposition)
        metric_records = [row for row in records if row["metric_code"] == metric_code]
        periods = [_period(row) for row in metric_records]
        entities = {_entity_id(row) for row in metric_records if _entity_id(row)}
        return DatasetInspection(
            dataset_id=metadata.dataset_id,
            dataset_version=metadata.version,
            topic=metadata.topic,
            grain=tuple(metadata.grain.dimensions),
            metric_code=metric_code,
            available_metrics=available_metrics,
            period_start=min(periods),
            period_end=max(periods),
            entity_count=len(entities),
            quality_score=metadata.quality_score,
        )


class QueryObservationsTool:
    """Run a typed read-only query and aggregate canonical rows by entity and period."""

    def __init__(self, query_engine_factory: QueryEngineFactory) -> None:
        self._query_engine_factory = query_engine_factory

    def execute(
        self,
        decomposition: DecomposedQuery,
        inspection: DatasetInspection,
        metadata: DatasetMetadata,
    ) -> ObservationSeries:
        if (
            metadata.status is not DatasetStatus.PUBLISHED
            or metadata.dataset_id != inspection.dataset_id
            or metadata.version != inspection.dataset_version
        ):
            raise QueryExecutionError(
                "observation query requires the inspected published dataset version"
            )
        filters = decomposition.filters
        dimensions = [*_INSPECTION_DIMENSIONS]
        if filters.age_lower is not None or filters.age_upper is not None:
            dimensions.extend(_AGE_DIMENSIONS)
        query_filters: dict[str, FilterValue] = {"metric_code": inspection.metric_code}
        if filters.gender_code is not None:
            # Pushed into the engine instead of projected. Adding gender to the
            # grouping multiplies the returned rows and trips the row guard on a
            # real dataset, while the engine can drop them before grouping.
            query_filters["gender_code"] = filters.gender_code
        result = self._query_engine_factory(metadata).execute(
            QuerySpec(
                table=inspection.dataset_id,
                dimensions=dimensions,
                metrics=["metric_value"],
                filters=query_filters,
                # Same reason as inspection. The per-entity, per-period summing below
                # is unchanged and stays correct: summing already-summed groups is
                # the same total.
                group_by_dimensions=True,
                max_rows=100_000,
            )
        )
        if result.truncated:
            raise QueryExecutionError("observation query exceeded the safe 100000-row query limit")
        records = _records(result.columns, result.rows)
        if not records and filters.gender_code is not None:
            # The canonical gender column is nullable, so a row that is not
            # broken down by gender cannot be attributed to one.
            raise QueryExecutionError("the dataset has no rows broken down by the requested gender")
        # Match on canonical district identity rather than on the literal
        # string, so a question about Tamsui, 淡水區, or Đạm Thủy reaches rows
        # keyed "12". Identifiers that are not districts compare as themselves.
        requested = {_entity_key(item): item for item in decomposition.entity_ids}
        if requested:
            records = [row for row in records if _entity_key(_entity_id(row)) in requested]
            found = {_entity_key(_entity_id(row)) for row in records}
            if missing := set(requested) - found:
                raise QueryExecutionError(
                    "no observations for requested entities: "
                    + ", ".join(sorted(requested[key] for key in missing))
                )
        # A wider band cannot be split without inventing numbers, so containment
        # is required and the filter names itself when it removes every row.
        by_age = _filter_age(records, filters.age_lower, filters.age_upper)
        if records and not by_age:
            raise QueryExecutionError(
                "the dataset has no age band contained in the requested age scope"
            )
        records = _filter_period(by_age, decomposition.time_expression)
        if not records:
            raise QueryExecutionError("no observations match the requested scope")
        units = {str(row["unit_code"]) for row in records}
        scopes = {str(row["population_scope"]) for row in records}
        if len(units) != 1 or len(scopes) != 1:
            raise QueryExecutionError("mixed units or population scopes cannot be compared safely")
        grouped: dict[tuple[str, str], ObservationPoint] = {}
        for row in records:
            entity_id = _entity_id(row)
            if not entity_id:
                continue
            key = (entity_id, _period(row))
            value = _number(row["metric_value"])
            current = grouped.get(key)
            if current is None:
                current = ObservationPoint(
                    entity_id=entity_id,
                    entity_name=_entity_name(row),
                    period=key[1],
                    value=0,
                    estimated_value=0,
                )
            grouped[key] = current.model_copy(
                update={
                    "value": round(current.value + value, 4),
                    "estimated_value": round(
                        current.estimated_value + (value if row["is_estimated"] is True else 0),
                        4,
                    ),
                }
            )
        points = tuple(grouped[key] for key in sorted(grouped, key=lambda item: (item[0], item[1])))
        points = _drop_structural_zero_sentinels(points, inspection.metric_code)
        if not points:
            raise QueryExecutionError("no entity-level observations are available")
        return ObservationSeries(
            dataset_id=inspection.dataset_id,
            dataset_version=inspection.dataset_version,
            metric_code=inspection.metric_code,
            unit_code=next(iter(units)),
            population_scope=next(iter(scopes)),
            points=points,
        )


def _drop_structural_zero_sentinels(
    points: tuple[ObservationPoint, ...], metric_code: str
) -> tuple[ObservationPoint, ...]:
    """Remove isolated zero placeholders from count series.

    A real population count cannot fall from tens of thousands to zero for one
    month and immediately recover. Some published files nevertheless encode a
    missing monthly sheet as zero in every component row. Only a zero strictly
    bracketed by positive observations for the same entity is removed; genuine
    leading, trailing, and sustained zero counts remain data.
    """

    if not metric_code.endswith("_count"):
        return points
    grouped: dict[str, list[ObservationPoint]] = {}
    for point in points:
        grouped.setdefault(point.entity_id, []).append(point)
    omitted: set[tuple[str, str]] = set()
    for entity_id, entity_points in grouped.items():
        ordered = sorted(entity_points, key=lambda point: point.period)
        for previous, current, following in zip(ordered, ordered[1:], ordered[2:], strict=False):
            if current.value == 0 and previous.value > 0 and following.value > 0:
                omitted.add((entity_id, current.period))
    return tuple(point for point in points if (point.entity_id, point.period) not in omitted)


class CompareEntitiesTool:
    """Calculate changes over one shared time window without model arithmetic."""

    def execute(self, series: ObservationSeries) -> EntityComparison:
        grouped: dict[str, list[ObservationPoint]] = {}
        for point in series.points:
            grouped.setdefault(point.entity_id, []).append(point)
        if not grouped:
            raise QueryExecutionError("at least one entity is required for comparison")
        common_periods = set.intersection(
            *({point.period for point in points} for points in grouped.values())
        )
        if len(common_periods) < 2:
            raise QueryExecutionError(
                "at least two common periods are required to compare entities safely"
            )
        first_period, last_period = min(common_periods), max(common_periods)
        changes: list[EntityChange] = []
        for entity_id in sorted(grouped):
            by_period = {point.period: point for point in grouped[entity_id]}
            first, last = by_period[first_period], by_period[last_period]
            absolute = round(last.value - first.value, 4)
            percent = None if first.value == 0 else round(absolute / first.value * 100, 2)
            direction = "increased" if absolute > 0 else "decreased" if absolute < 0 else "flat"
            changes.append(
                EntityChange(
                    entity_id=entity_id,
                    entity_name=last.entity_name or first.entity_name,
                    first_period=first.period,
                    last_period=last.period,
                    first_value=first.value,
                    last_value=last.value,
                    absolute_change=absolute,
                    percent_change=percent,
                    direction=direction,
                    observation_count=2,
                )
            )
        return EntityComparison(
            metric_code=series.metric_code,
            unit_code=series.unit_code,
            changes=tuple(changes),
        )


class ObservationToolSuite:
    """Runtime bundle exposing the three independently testable observation tools."""

    def __init__(
        self, catalog: DatasetCatalogReader, query_engine_factory: QueryEngineFactory
    ) -> None:
        self.catalog = catalog
        self.inspect_dataset = InspectDatasetTool(catalog, query_engine_factory)
        self.query_observations = QueryObservationsTool(query_engine_factory)
        self.compare_entities = CompareEntitiesTool()


def _select_dataset(
    candidates: list[DatasetMetadata], decomposition: DecomposedQuery
) -> DatasetMetadata:
    if not candidates:
        raise QueryExecutionError("no published dataset satisfies the requested quality")
    if len(candidates) == 1:
        return candidates[0]
    terms = set(decomposition.subject_terms) | set(decomposition.metric_terms)
    ranked = sorted(
        (
            (_relevance(item, terms), item.quality_score, item.dataset_id, item)
            for item in candidates
        ),
        key=lambda value: (-value[0], -value[1], value[2]),
    )
    if ranked[0][0] == 0:
        raise QueryExecutionError(
            "multiple published datasets match the scope; specify a metric or topic"
        )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise QueryExecutionError("dataset selection is ambiguous; specify the dataset topic")
    return ranked[0][3]


def _relevance(metadata: DatasetMetadata, terms: set[str]) -> int:
    haystack = set(_tokens(f"{metadata.dataset_id} {metadata.topic}"))
    return len(haystack & {token for term in terms for token in _tokens(term)})


def _select_metric(metrics: tuple[str, ...], decomposition: DecomposedQuery) -> str:
    requested = set(decomposition.metric_terms) | set(decomposition.subject_terms)
    requested_tokens = {token for term in requested for token in _tokens(term)}
    scored = sorted(
        ((len(set(_tokens(metric)) & requested_tokens), metric) for metric in metrics),
        key=lambda item: (-item[0], item[1]),
    )
    if len(metrics) == 1:
        return metrics[0]
    if not scored or scored[0][0] == 0:
        raise QueryExecutionError("multiple metrics are available; specify the metric code")
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise QueryExecutionError("metric selection is ambiguous; specify the metric code")
    return scored[0][1]


def _records(columns: list[str], rows: list[list[CellValue]]) -> list[dict[str, object]]:
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value.casefold().replace("_", " ")))


def _period(row: dict[str, object]) -> str:
    year = _year(row)
    month = row["month"]
    if month is None:
        return f"{year:04d}"
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise QueryExecutionError("month must be an integer from 1 to 12")
    return f"{year:04d}-{month:02d}"


def _entity_id(row: dict[str, object]) -> str:
    return str(row["district_code"] or row["city_code"] or "")


def _entity_key(value: str) -> str:
    """Collapse every spelling of one district onto a single comparison key."""

    district = resolve_district_name(value).district
    return district.code if district is not None else value.casefold()


def _entity_name(row: dict[str, object]) -> str | None:
    value = row["district_name"] or row["city_name"]
    return str(value) if value else None


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise QueryExecutionError("metric_value is not numeric")
    return float(value)


def _filter_period(
    records: list[dict[str, object]], expression: str | None
) -> list[dict[str, object]]:
    if not expression:
        return records
    years = [int(value) for value in _YEAR.findall(expression)]
    if years:
        start, end = (min(years), max(years)) if len(years) > 1 else (years[0], years[0])
        return [row for row in records if start <= _year(row) <= end]
    match = _LAST_YEARS.search(expression.casefold())
    if match:
        count = int(match.group(1) or match.group(2) or match.group(3))
        latest = max(_year(row) for row in records)
        return [row for row in records if _year(row) > latest - count]
    return records


def _filter_age(
    records: list[dict[str, object]], lower: int | None, upper: int | None
) -> list[dict[str, object]]:
    if lower is None and upper is None:
        return records
    requested_lower = lower if lower is not None else 0
    requested_upper = upper if upper is not None else 120
    selected: list[dict[str, object]] = []
    for row in records:
        row_lower = row.get("age_lower")
        row_upper = row.get("age_upper")
        if (
            isinstance(row_lower, int)
            and not isinstance(row_lower, bool)
            and isinstance(row_upper, int)
            and not isinstance(row_upper, bool)
            and row_lower >= requested_lower
            and row_upper <= requested_upper
        ):
            selected.append(row)
    return selected


def _year(row: dict[str, object]) -> int:
    value = row["year_gregorian"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryExecutionError("year_gregorian is required for trend analysis")
    return value
