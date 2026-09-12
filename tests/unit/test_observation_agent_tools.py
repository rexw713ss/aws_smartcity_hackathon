"""Deterministic contracts for generic observation analysis tools."""

import pytest

from youth_compass.agent import (
    CompareEntitiesTool,
    EntityComparison,
    ObservationPoint,
    ObservationSeries,
)
from youth_compass.domain import QueryExecutionError


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


def test_compare_entities_requires_two_periods_per_entity() -> None:
    with pytest.raises(QueryExecutionError, match="at least two periods"):
        CompareEntitiesTool().execute(
            _series(
                ObservationPoint(
                    entity_id="a", period="2025", value=100, estimated_value=0
                )
            )
        )
