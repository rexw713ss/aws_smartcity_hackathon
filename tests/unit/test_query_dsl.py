"""The query DSL refuses by construction what ad-hoc checks refused by accident."""

import pytest

from youth_compass.agent.contracts import DatasetInspection
from youth_compass.agent.query_dsl import (
    Aggregation,
    Dimension,
    ObservationQuery,
    translate,
    validate,
)
from youth_compass.domain.errors import QueryNotPermittedError


def _inspection(
    *,
    metrics: tuple[str, ...] = ("population_count",),
    grain: tuple[str, ...] = ("district", "age_band", "gender", "month"),
) -> DatasetInspection:
    return DatasetInspection(
        dataset_id="youth_population",
        dataset_version="v1",
        topic="population",
        grain=grain,
        metric_code=metrics[0],
        available_metrics=metrics,
        period_start="2023-01",
        period_end="2025-12",
        entity_count=29,
        quality_score=0.9,
    )


def test_a_metric_the_dataset_does_not_publish_cannot_reach_the_engine() -> None:
    """The structural form of the bug where unemployment was answered with population."""

    query = ObservationQuery(metric_code="unemployment_count")

    with pytest.raises(QueryNotPermittedError, match="does not publish metric"):
        validate(query, _inspection())


def test_the_refusal_names_what_is_available_so_the_gap_is_actionable() -> None:
    query = ObservationQuery(metric_code="unemployment_count")

    with pytest.raises(QueryNotPermittedError, match="population_count"):
        validate(query, _inspection())


def test_a_breakdown_the_dataset_was_not_published_at_is_refused() -> None:
    """Grouping by an absent column yields confident rows, not an engine error.

    A table with no gender column grouped by gender returns one row per entity
    labelled as though gender had been considered. That is quieter than a crash
    and worse than one.
    """

    query = ObservationQuery(
        metric_code="population_count",
        group_by=(Dimension.DISTRICT, Dimension.GENDER),
    )

    with pytest.raises(QueryNotPermittedError, match="not published by gender"):
        validate(query, _inspection(grain=("district", "month")))


def test_period_never_needs_the_grain_to_justify_it() -> None:
    """Every canonical row carries a period, so a period breakdown is always valid."""

    query = ObservationQuery(metric_code="population_count", group_by=(Dimension.PERIOD,))

    assert validate(query, _inspection(grain=("district",))) is query


def test_translation_projects_only_canonical_columns_and_pushes_the_metric_filter() -> None:
    query = ObservationQuery(
        metric_code="population_count",
        group_by=(Dimension.DISTRICT, Dimension.PERIOD),
    )

    spec = translate(validate(query, _inspection()), _inspection())

    assert spec.table == "youth_population"
    assert spec.metrics == ["metric_value"]
    assert spec.filters == {"metric_code": "population_count"}
    assert spec.group_by_dimensions is True
    # The interpreting columns ride along on every query: a unit or scope that
    # varies inside one result makes the numbers incomparable, and the caller has
    # to be able to see that rather than average over it.
    assert {"unit_code", "population_scope", "metric_code"} <= set(spec.dimensions)
    assert {"district_code", "district_name", "year_gregorian", "month"} <= set(spec.dimensions)


def test_a_gender_filter_is_pushed_down_rather_than_grouped() -> None:
    """Grouping multiplies returned rows; filtering before grouping does not."""

    query = ObservationQuery(metric_code="population_count", gender_code="female")

    spec = translate(validate(query, _inspection()), _inspection())

    assert spec.filters["gender_code"] == "female"
    assert "gender_code" not in spec.dimensions


def test_only_sum_is_a_registered_aggregation() -> None:
    """Canonical facts are disjoint parts, so a sum is the only always-valid combine."""

    assert [item.value for item in Aggregation] == ["sum"]


def test_an_unknown_field_is_rejected_rather_than_silently_dropped() -> None:
    """This shape is filled by a model, so a stray field is a signal, not noise."""

    with pytest.raises(ValueError, match=r"extra_forbidden|Extra inputs"):
        ObservationQuery(metric_code="population_count", order_by="metric_value DESC")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"year_from": 2025, "year_to": 2023}, "year_from must not exceed year_to"),
        ({"age_lower": 40, "age_upper": 18}, "age_lower must not exceed age_upper"),
        ({"group_by": ()}, "at least one dimension"),
        (
            {"group_by": (Dimension.DISTRICT, Dimension.DISTRICT)},
            "must not repeat a dimension",
        ),
    ],
)
def test_incoherent_requests_are_refused_at_the_boundary(
    fields: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ObservationQuery(metric_code="population_count", **fields)  # type: ignore[arg-type]
