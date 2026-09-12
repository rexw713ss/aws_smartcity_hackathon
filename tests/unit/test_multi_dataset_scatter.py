"""The relationship view for a two-dataset join. Doc 30, stage 3."""

from youth_compass.agent.contracts import (
    ObservationPoint,
    ObservationSeries,
    VisualizationType,
)
from youth_compass.agent.multi_dataset import _scatter
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)


def _metadata(dataset_id: str, topic: str) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id=dataset_id,
        version="v1",
        source_uri=f"s3://curated/{dataset_id}/version=v1/part-000.parquet",
        source_sha256="a" * 64,
        topic=topic,
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.95,
    )


def _series(metric_code: str, unit_code: str) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="d",
        dataset_version="v1",
        metric_code=metric_code,
        unit_code=unit_code,
        population_scope="youth_specific",
        points=(ObservationPoint(entity_id="01", period="2025", value=1.0, estimated_value=0.0),),
    )


def _rows(count: int) -> list[dict[str, str | int | float | bool | None]]:
    return [
        {
            "entity_name": f"District {index}",
            "period": "2025",
            "metric_1": float(100 + index * 10),
            "metric_2": float(50 - index),
        }
        for index in range(count)
    ]


def _pair() -> list[tuple[DatasetMetadata, ObservationSeries]]:
    return [
        (_metadata("youth_population", "population"), _series("population_count", "persons")),
        (_metadata("youth_employment", "employment"), _series("employment_count", "persons")),
    ]


def test_two_joined_metrics_are_plotted_against_each_other() -> None:
    spec = _scatter(_pair(), _rows(6), "2025", ("data-1", "data-2"))

    assert spec is not None
    assert spec.type is VisualizationType.SCATTER
    assert spec.x is not None and spec.x.field == "metric_1"
    assert spec.y is not None and spec.y.field == "metric_2"
    assert len(spec.rows) == 6
    assert spec.citation_ids == ("data-1", "data-2")


def test_the_scatter_states_that_it_is_not_a_causal_claim() -> None:
    spec = _scatter(_pair(), _rows(6), "2025", ("data-1",))

    assert spec is not None
    assert spec.description is not None
    assert "not" in spec.description and "causes" in spec.description


def test_too_few_districts_do_not_earn_a_relationship_view() -> None:
    assert _scatter(_pair(), _rows(3), "2025", ("data-1",)) is None


def test_three_joined_datasets_have_no_single_pair_to_plot() -> None:
    trio = [*_pair(), (_metadata("housing", "housing"), _series("housing_count", "units"))]

    assert _scatter(trio, _rows(6), "2025", ("data-1",)) is None


def test_rows_missing_either_metric_are_dropped_rather_than_placed_at_zero() -> None:
    rows = _rows(5)
    rows.append({"entity_name": "Partial", "period": "2025", "metric_1": 120.0, "metric_2": None})

    spec = _scatter(_pair(), rows, "2025", ("data-1",))

    assert spec is not None
    assert all(row["entity_name"] != "Partial" for row in spec.rows)
