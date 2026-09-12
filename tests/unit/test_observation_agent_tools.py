"""Deterministic contracts for generic observation analysis tools."""

import pytest

from youth_compass.agent import (
    AnalysisFilters,
    AnalysisOperation,
    CompareEntitiesTool,
    DatasetInspection,
    DecomposedQuery,
    EntityComparison,
    ObservationPoint,
    ObservationSeries,
    QueryObservationsTool,
)
from youth_compass.domain import QueryExecutionError
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)
from youth_compass.ports import QuerySpec
from youth_compass.ports.query_engine import QueryResult


def _series(*points: ObservationPoint) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=points,
    )


def test_compare_entities_calculates_change_without_model_arithmetic() -> None:
    result: EntityComparison = CompareEntitiesTool().execute(
        _series(
            ObservationPoint(entity_id="a", period="2024", value=100, estimated_value=0),
            ObservationPoint(entity_id="a", period="2025", value=125, estimated_value=0),
            ObservationPoint(entity_id="b", period="2024", value=80, estimated_value=0),
            ObservationPoint(entity_id="b", period="2025", value=72, estimated_value=0),
        )
    )

    assert result.changes[0].absolute_change == 25
    assert result.changes[0].percent_change == 25
    assert result.changes[0].direction == "increased"
    assert result.changes[1].percent_change == -10
    assert result.changes[1].direction == "decreased"


def test_compare_entities_requires_two_common_periods() -> None:
    with pytest.raises(QueryExecutionError, match="at least two common periods"):
        CompareEntitiesTool().execute(
            _series(ObservationPoint(entity_id="a", period="2025", value=100, estimated_value=0))
        )


def test_compare_entities_uses_the_same_endpoints_for_every_entity() -> None:
    result = CompareEntitiesTool().execute(
        _series(
            ObservationPoint(entity_id="a", period="2023", value=90, estimated_value=0),
            ObservationPoint(entity_id="a", period="2024", value=100, estimated_value=0),
            ObservationPoint(entity_id="a", period="2025", value=125, estimated_value=0),
            ObservationPoint(entity_id="b", period="2024", value=80, estimated_value=0),
            ObservationPoint(entity_id="b", period="2025", value=72, estimated_value=0),
            ObservationPoint(entity_id="b", period="2026", value=70, estimated_value=0),
        )
    )

    assert {(item.first_period, item.last_period) for item in result.changes} == {("2024", "2025")}
    assert result.changes[0].absolute_change == 25
    assert result.changes[1].absolute_change == -8


class RecordingQueryEngine:
    """Capture the typed QuerySpec the tool builds, then replay fixed rows."""

    def __init__(self, columns: list[str], rows: list[list[object]]) -> None:
        self.columns = columns
        self.rows = rows
        self.specs: list[QuerySpec] = []

    def execute(self, spec: QuerySpec) -> QueryResult:
        self.specs.append(spec)
        return QueryResult(columns=self.columns, rows=self.rows, row_count=len(self.rows))


_DIMENSIONS = [
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


def _row(year: int, value: float) -> list[object]:
    return [
        year,
        None,
        "ntpc",
        "New Taipei City",
        "01",
        "板橋區",
        "population_count",
        "persons",
        "youth_specific",
        False,
        value,
    ]


def _observation_metadata() -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="population",
        version="v1",
        source_uri="fileobj://incoming/population.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=1.0,
    )


def _observation_inspection() -> DatasetInspection:
    return DatasetInspection(
        dataset_id="population",
        dataset_version="v1",
        topic="population",
        grain=("year_gregorian", "district_code"),
        metric_code="population_count",
        available_metrics=("population_count",),
        period_start="2024",
        period_end="2025",
        entity_count=1,
        quality_score=1.0,
    )


def _observation_query(filters: AnalysisFilters) -> DecomposedQuery:
    return DecomposedQuery(
        original_question="Compare population",
        objective="compare observations",
        metric_terms=("population_count",),
        filters=filters,
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )


def test_a_gender_filter_is_pushed_into_the_query_not_projected() -> None:
    # Projecting gender into the grouping multiplied the returned rows and
    # tripped the 100000-row guard on the real published dataset.
    engine = RecordingQueryEngine(
        [*_DIMENSIONS, "metric_value"], [_row(2024, 100), _row(2025, 120)]
    )

    QueryObservationsTool(lambda _metadata: engine).execute(
        _observation_query(AnalysisFilters(gender_code="female")),
        _observation_inspection(),
        _observation_metadata(),
    )

    spec = engine.specs[-1]
    assert spec.filters["gender_code"] == "female"
    assert "gender_code" not in spec.dimensions


def test_an_age_filter_projects_the_band_columns_it_must_compare() -> None:
    # An age band cannot be expressed as an equality filter, so containment is
    # applied after the scan and the columns must be selected.
    engine = RecordingQueryEngine(
        [*_DIMENSIONS, "metric_value"], [_row(2024, 100), _row(2025, 120)]
    )

    with pytest.raises(QueryExecutionError, match="age band"):
        QueryObservationsTool(lambda _metadata: engine).execute(
            _observation_query(AnalysisFilters(age_lower=20, age_upper=29)),
            _observation_inspection(),
            _observation_metadata(),
        )

    spec = engine.specs[-1]
    assert "age_lower" in spec.dimensions and "age_upper" in spec.dimensions
    assert "gender_code" not in spec.filters


def test_an_isolated_zero_count_between_positive_months_is_treated_as_missing() -> None:
    rows = []
    for month, value in ((8, 26131), (9, 0), (10, 26193)):
        row = _row(2019, value)
        row[1] = month
        row[4] = "17"
        row[5] = "林口區"
        rows.append(row)
    engine = RecordingQueryEngine([*_DIMENSIONS, "metric_value"], rows)

    series = QueryObservationsTool(lambda _metadata: engine).execute(
        _observation_query(AnalysisFilters()),
        _observation_inspection(),
        _observation_metadata(),
    )

    assert [(point.period, point.value) for point in series.points] == [
        ("2019-08", 26131),
        ("2019-10", 26193),
    ]


def test_an_unmatched_gender_filter_names_the_filter_that_emptied_the_result() -> None:
    engine = RecordingQueryEngine([*_DIMENSIONS, "metric_value"], [])

    with pytest.raises(QueryExecutionError, match="broken down by the requested gender"):
        QueryObservationsTool(lambda _metadata: engine).execute(
            _observation_query(AnalysisFilters(gender_code="male")),
            _observation_inspection(),
            _observation_metadata(),
        )


def _catalog_entry(dataset_id: str, topic: str) -> DatasetMetadata:
    return _observation_metadata().model_copy(update={"dataset_id": dataset_id, "topic": topic})


def _selection_query(question: str, **fields: object) -> DecomposedQuery:
    return DecomposedQuery(
        original_question=question,
        objective="compare observations",
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
        **fields,  # type: ignore[arg-type]
    )


def test_a_question_naming_no_subject_defaults_to_population() -> None:
    # Publishing a second table made "Compare Shimen and Linkou" ambiguous.
    from youth_compass.agent.observation_tools import _select_dataset

    catalog = [_catalog_entry("education", "education"), _catalog_entry("population", "population")]

    selected = _select_dataset(
        catalog, _selection_query("Compare Shimen and Linkou from 2018 to 2025")
    )

    assert selected.dataset_id == "population"


def test_a_subject_named_in_vietnamese_selects_its_table() -> None:
    from youth_compass.agent.observation_tools import _select_dataset

    catalog = [_catalog_entry("population", "population"), _catalog_entry("education", "education")]

    selected = _select_dataset(catalog, _selection_query("Trình độ học vấn ở Bản Kiều"))

    assert selected.dataset_id == "education"


def test_no_default_is_guessed_when_population_is_not_published() -> None:
    from youth_compass.agent.observation_tools import _select_dataset

    catalog = [_catalog_entry("education", "education"), _catalog_entry("income", "income")]

    with pytest.raises(QueryExecutionError, match="specify a metric or topic"):
        _select_dataset(catalog, _selection_query("Compare Shimen and Linkou"))
