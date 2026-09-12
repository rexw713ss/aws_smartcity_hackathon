"""The visualization rubric, and a small suite run through the real builder.

Doc 30, stage 6.
"""

import pytest

from youth_compass.agent import (
    AnalysisOperation,
    DecomposedQuery,
    ObservationPoint,
    ObservationSeries,
    VisualizationBuilder,
    VisualizationType,
    choose_measure,
    profile_series,
)
from youth_compass.agent.measures import Transform
from youth_compass.agent.viz_evals import (
    RubricDimension,
    VisualizationEvalCase,
    grade_visualizations,
)


def _series(values: dict[str, dict[str, float]]) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=tuple(
            ObservationPoint(
                entity_id=entity,
                entity_name=entity.title(),
                period=period,
                value=value,
                estimated_value=0.0,
            )
            for entity, points in values.items()
            for period, value in points.items()
        ),
    )


def _query(question: str, *operations: AnalysisOperation) -> DecomposedQuery:
    return DecomposedQuery(
        original_question=question,
        objective="describe the change",
        operations=operations or (AnalysisOperation.QUERY_OBSERVATIONS,),
    )


def _run(case: VisualizationEvalCase, values: dict[str, dict[str, float]]) -> tuple[object, ...]:
    """Build through the production path, then grade what it produced."""

    series = _series(values)
    decomposition = _query(case.question)
    profile = profile_series(series)
    measure = choose_measure(profile, decomposition)
    specs = VisualizationBuilder().observations(
        case.question,
        series,
        None,
        ("data-1",),
        decomposition=decomposition,
        measure=measure,
        profile=profile,
    )
    return grade_visualizations(case, specs, profile=profile, measure=measure), specs


def test_a_real_trend_passes_every_dimension() -> None:
    case = VisualizationEvalCase(
        case_id="youth-decline-trend",
        question="How has the youth population changed?",
        expected_type=VisualizationType.LINE,
    )

    result, _ = _run(
        case,
        {
            "banqiao": {"2020": 1000.0, "2021": 940.0, "2022": 860.0},
            "xindian": {"2020": 900.0, "2021": 880.0, "2022": 870.0},
        },
    )

    assert result.passed, result.failures
    assert {item.dimension for item in result.scores} == set(RubricDimension)


def test_a_flat_result_is_expected_to_produce_no_chart_at_all() -> None:
    case = VisualizationEvalCase(
        case_id="flat-population",
        question="How has the youth population changed?",
        expect_no_chart=True,
    )

    result, specs = _run(
        case,
        {
            "banqiao": {"2020": 1000.0, "2021": 1001.0, "2022": 1002.0},
            "xindian": {"2020": 900.0, "2021": 901.0, "2022": 900.0},
        },
    )

    assert result.passed, result.failures
    assert specs == ()


def test_expecting_no_chart_fails_when_one_is_drawn_anyway() -> None:
    case = VisualizationEvalCase(
        case_id="wrongly-flat",
        question="How has the youth population changed?",
        expect_no_chart=True,
    )

    result, _ = _run(
        case,
        {
            "banqiao": {"2020": 1000.0, "2021": 700.0, "2022": 500.0},
            "xindian": {"2020": 900.0, "2021": 600.0, "2022": 400.0},
        },
    )

    assert not result.passed
    assert "goal_compliance" in result.failures[0]


def test_a_wide_spread_is_expected_to_be_indexed_and_the_rubric_checks_it() -> None:
    case = VisualizationEvalCase(
        case_id="uneven-districts",
        question="How has the youth population changed?",
        expected_type=VisualizationType.LINE,
        expected_transform=Transform.INDEX_100,
    )

    result, _ = _run(
        case,
        {
            "banqiao": {"2020": 50000.0, "2021": 49000.0, "2022": 47000.0},
            "pinglin": {"2020": 500.0, "2021": 420.0, "2022": 300.0},
        },
    )

    assert result.passed, result.failures


def test_the_wrong_measure_fails_the_unit_dimension() -> None:
    case = VisualizationEvalCase(
        case_id="expects-a-rate",
        question="How has the youth population changed?",
        expected_transform=Transform.PER_1000,
    )

    result, _ = _run(
        case,
        {
            "banqiao": {"2020": 50000.0, "2021": 47000.0},
            "pinglin": {"2020": 500.0, "2021": 300.0},
        },
    )

    assert not result.passed
    assert any("unit_appropriateness" in failure for failure in result.failures)


def test_a_missing_headline_fails_goal_compliance() -> None:
    series = _series({"banqiao": {"2020": 1000.0, "2021": 700.0}})
    profile = profile_series(series)
    specs = VisualizationBuilder().observations(
        "How has the youth population changed?", series, None, ("data-1",), profile=profile
    )
    stripped = tuple(spec.model_copy(update={"headline": None}) for spec in specs)
    case = VisualizationEvalCase(
        case_id="headless",
        question="How has the youth population changed?",
    )

    result = grade_visualizations(case, stripped, profile=profile)

    assert not result.passed
    assert any("states no finding" in failure for failure in result.failures)


def test_a_case_expecting_a_chart_fails_when_the_agent_declines() -> None:
    case = VisualizationEvalCase(
        case_id="expected-a-chart",
        question="How has the youth population changed?",
    )
    profile = profile_series(_series({"banqiao": {"2020": 1.0, "2021": 1.0}}))

    result = grade_visualizations(case, (), profile=profile)

    assert not result.passed
    assert "expected a chart" in result.failures[0]


@pytest.mark.parametrize(
    ("case_id", "question", "expected"),
    [
        ("two-period-slope", "How has the youth population changed?", VisualizationType.SLOPE),
        ("spatial", "Where did the youth population fall the most?", VisualizationType.LINE),
    ],
)
def test_representative_questions_reach_their_expected_template(
    case_id: str, question: str, expected: VisualizationType
) -> None:
    values = (
        {
            "banqiao": {"2021": 1000.0, "2022": 700.0},
            "xindian": {"2021": 900.0, "2022": 940.0},
            "sanchong": {"2021": 800.0, "2022": 600.0},
        }
        if expected is VisualizationType.SLOPE
        else {
            "banqiao": {"2020": 1000.0, "2021": 900.0, "2022": 700.0},
            "xindian": {"2020": 900.0, "2021": 880.0, "2022": 870.0},
        }
    )
    case = VisualizationEvalCase(case_id=case_id, question=question, expected_type=expected)

    result, _ = _run(case, values)

    assert result.passed, result.failures
