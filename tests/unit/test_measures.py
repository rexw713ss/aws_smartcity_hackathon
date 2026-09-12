"""Unit selection that makes a comparison mean something. Doc 30, stage 2."""

import pytest

from youth_compass.agent.contracts import (
    AnalysisOperation,
    DecomposedQuery,
    ObservationPoint,
    ObservationSeries,
)
from youth_compass.agent.data_shape import profile_series
from youth_compass.agent.measures import (
    Transform,
    apply_measure,
    choose_measure,
)
from youth_compass.ontology import NameLanguage


def _series(
    points: tuple[ObservationPoint, ...],
    *,
    metric_code: str = "population_count",
    unit_code: str = "persons",
) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code=metric_code,
        unit_code=unit_code,
        population_scope="youth_specific",
        points=points,
    )


def _point(entity_id: str, period: str, value: float) -> ObservationPoint:
    return ObservationPoint(
        entity_id=entity_id,
        entity_name=entity_id.title(),
        period=period,
        value=value,
        estimated_value=0.0,
    )


def _trend(entity_id: str, values: dict[str, float]) -> tuple[ObservationPoint, ...]:
    return tuple(_point(entity_id, period, value) for period, value in values.items())


def _query(*operations: AnalysisOperation) -> DecomposedQuery:
    return DecomposedQuery(
        original_question="how did the youth population change",
        objective="describe the change",
        operations=operations or (AnalysisOperation.QUERY_OBSERVATIONS,),
    )


def _monthly(
    entity_id: str, start_year: int, years: int, value: float
) -> tuple[ObservationPoint, ...]:
    return tuple(
        _point(entity_id, f"{start_year + offset}-{month:02d}", value + offset * 10 + month)
        for offset in range(years)
        for month in range(1, 13)
    )


# Selection


def test_entities_of_comparable_size_keep_their_published_unit() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 1000.0, "2023": 1100.0}),
            *_trend("xindian", {"2022": 800.0, "2023": 860.0}),
        )
    )

    measure = choose_measure(profile_series(series), _query())

    assert measure.transform is Transform.RAW
    assert measure.unit_code == "persons"


def test_entities_of_wildly_different_size_are_indexed_to_their_own_baseline() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 500.0, "2023": 400.0}),
        )
    )
    profile = profile_series(series)

    measure = choose_measure(profile, _query())

    assert measure.transform is Transform.INDEX_100
    assert measure.unit_code == "index_100"
    assert measure.baseline_period == "2022"


def test_a_comparison_question_over_uneven_entities_collapses_to_a_percentage() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 500.0, "2023": 400.0}),
        )
    )

    measure = choose_measure(
        profile_series(series),
        _query(AnalysisOperation.QUERY_OBSERVATIONS, AnalysisOperation.COMPARE_ENTITIES),
    )

    assert measure.transform is Transform.PCT_CHANGE
    assert measure.unit_code == "percent"


def test_a_comparison_question_over_even_entities_keeps_absolute_values() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 1000.0, "2023": 900.0}),
            *_trend("xindian", {"2022": 800.0, "2023": 700.0}),
        )
    )

    measure = choose_measure(
        profile_series(series),
        _query(AnalysisOperation.QUERY_OBSERVATIONS, AnalysisOperation.COMPARE_ENTITIES),
    )

    assert measure.transform is Transform.RAW


def test_a_multi_year_monthly_series_is_compared_with_the_same_month_last_year() -> None:
    series = _series(_monthly("banqiao", 2022, 3, 1000.0))

    measure = choose_measure(profile_series(series), _query())

    assert measure.transform is Transform.YOY_CHANGE


def test_a_single_year_monthly_series_has_no_prior_year_to_compare_with() -> None:
    series = _series(_monthly("banqiao", 2022, 1, 1000.0))

    assert choose_measure(profile_series(series), _query()).transform is Transform.RAW


def test_a_rate_is_chosen_only_when_every_entity_has_a_denominator() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 500.0, "2023": 400.0}),
        )
    )
    profile = profile_series(series)

    complete = choose_measure(
        profile, _query(), denominators={"banqiao": 550000.0, "pinglin": 6000.0}
    )
    partial = choose_measure(profile, _query(), denominators={"banqiao": 550000.0})

    assert complete.transform is Transform.PER_1000
    assert partial.transform is Transform.INDEX_100


def test_the_rationale_is_written_in_the_language_of_the_question() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 500.0, "2023": 400.0}),
        )
    )
    profile = profile_series(series)

    vietnamese = choose_measure(profile, _query(), language=NameLanguage.VIETNAMESE)
    chinese = choose_measure(profile, _query(), language=NameLanguage.ZH_HANT)

    assert "Chỉ số" in vietnamese.label
    assert "指數" in chinese.label
    assert vietnamese.rationale != chinese.rationale


# Application


def test_raw_leaves_every_published_value_untouched() -> None:
    series = _series(_trend("banqiao", {"2022": 100.0, "2023": 110.0}))
    measure = choose_measure(profile_series(series), _query())

    points = apply_measure(series, measure)

    assert [point.value for point in points] == [100.0, 110.0]
    assert [point.source_value for point in points] == [100.0, 110.0]


def test_an_index_restates_each_entity_against_its_own_first_value() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 500.0, "2023": 400.0}),
        )
    )
    measure = choose_measure(profile_series(series), _query())

    values = {
        (point.entity_id, point.period): round(point.value, 2)
        for point in apply_measure(series, measure)
    }

    assert values[("banqiao", "2022")] == 100.0
    assert values[("pinglin", "2022")] == 100.0
    assert values[("banqiao", "2023")] == 98.0
    # The small district's much steeper fall is what the index exists to reveal.
    assert values[("pinglin", "2023")] == 80.0


def test_an_entity_whose_baseline_is_zero_is_dropped_rather_than_given_a_denominator() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022": 50000.0, "2023": 49000.0}),
            *_trend("pinglin", {"2022": 0.0, "2023": 400.0}),
        )
    )
    measure = choose_measure(profile_series(series), _query())

    points = apply_measure(series, measure)

    assert {point.entity_id for point in points} == {"banqiao"}


def test_a_percentage_change_collapses_each_entity_to_its_final_period() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2020": 1000.0, "2021": 900.0, "2022": 800.0}),
            *_trend("pinglin", {"2020": 100.0, "2021": 60.0, "2022": 50.0}),
        )
    )
    measure = choose_measure(
        profile_series(series),
        _query(AnalysisOperation.QUERY_OBSERVATIONS, AnalysisOperation.COMPARE_ENTITIES),
    )

    points = apply_measure(series, measure)

    assert {point.period for point in points} == {"2022"}
    assert {point.entity_id: round(point.value, 1) for point in points} == {
        "banqiao": -20.0,
        "pinglin": -50.0,
    }


def test_year_on_year_compares_each_month_with_the_same_month_a_year_earlier() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2022-01": 100.0, "2022-02": 200.0}),
            *_trend("banqiao", {"2023-01": 110.0, "2023-02": 180.0}),
        )
    )
    measure = choose_measure(profile_series(series), _query())
    points = apply_measure(series, measure)

    assert measure.transform is Transform.YOY_CHANGE
    # The first year has no prior year, so it produces no comparison at all.
    assert {point.period: round(point.value, 1) for point in points} == {
        "2023-01": 10.0,
        "2023-02": -10.0,
    }


def test_a_share_sums_to_one_hundred_within_each_period() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2023": 75.0}),
            *_trend("xindian", {"2023": 25.0}),
        )
    )
    measure = choose_measure(profile_series(series), _query()).model_copy(
        update={"transform": Transform.SHARE_OF_TOTAL}
    )

    points = apply_measure(series, measure)

    assert round(sum(point.value for point in points), 6) == 100.0


def test_a_rate_divides_by_each_entitys_own_denominator() -> None:
    series = _series(
        (
            *_trend("banqiao", {"2023": 55000.0}),
            *_trend("pinglin", {"2023": 600.0}),
        )
    )
    denominators = {"banqiao": 550000.0, "pinglin": 6000.0}
    measure = choose_measure(profile_series(series), _query(), denominators=denominators)

    points = apply_measure(series, measure, denominators=denominators)

    assert {point.entity_id: round(point.value, 1) for point in points} == {
        "banqiao": 100.0,
        "pinglin": 100.0,
    }


def test_a_rate_without_denominators_fails_instead_of_plotting_nothing() -> None:
    series = _series(_trend("banqiao", {"2023": 55000.0}))
    measure = choose_measure(profile_series(series), _query()).model_copy(
        update={"transform": Transform.PER_1000}
    )

    with pytest.raises(ValueError, match="denominator"):
        apply_measure(series, measure)
