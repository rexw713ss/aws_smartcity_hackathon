"""Scoring that keeps the chart worth drawing. Doc 30, stage 4."""

from youth_compass.agent.contracts import (
    ObservationPoint,
    ObservationSeries,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.data_shape import profile_series
from youth_compass.agent.viz_selection import (
    CandidateRole,
    RejectionReason,
    VisualizationCandidate,
    informativeness,
    role_for,
    select_visualizations,
)


def _line(visualization_id: str, values: dict[str, dict[str, float]]) -> VisualizationSpec:
    return VisualizationSpec(
        visualization_id=visualization_id,
        type=VisualizationType.LINE,
        title="Trend",
        x={"field": "period", "label": "Period", "data_type": "temporal"},
        y={"field": "value", "label": "Value", "data_type": "quantitative"},
        series_field="entity_name",
        rows=tuple(
            {"period": period, "entity_name": entity, "value": value}
            for entity, points in values.items()
            for period, value in points.items()
        ),
    )


def _bar(visualization_id: str, values: dict[str, float]) -> VisualizationSpec:
    return VisualizationSpec(
        visualization_id=visualization_id,
        type=VisualizationType.COMPARISON_BAR,
        title="Change",
        x={"field": "entity_name", "label": "Entity", "data_type": "nominal"},
        y={"field": "value", "label": "Value", "data_type": "quantitative"},
        rows=tuple({"entity_name": entity, "value": value} for entity, value in values.items()),
    )


def _table(visualization_id: str) -> VisualizationSpec:
    return VisualizationSpec(
        visualization_id=visualization_id,
        type=VisualizationType.DATA_TABLE,
        title="Rows",
        columns=({"field": "value", "label": "Value", "unit": None},),
        rows=({"value": 1.0},),
    )


def _series(points: tuple[ObservationPoint, ...]) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=points,
    )


def test_a_line_through_a_series_that_barely_moves_is_rejected() -> None:
    candidate = VisualizationCandidate(
        spec=_line("flat", {"Banqiao": {"2022": 1000.0, "2023": 1002.0}}),
        role=CandidateRole.TREND,
    )

    result = select_visualizations((candidate,))

    assert result.selected == ()
    assert result.rejected[0].reason is RejectionReason.WEAK_SIGNAL
    assert "not there" in result.rejected[0].detail


def test_a_line_through_a_real_movement_is_kept() -> None:
    candidate = VisualizationCandidate(
        spec=_line("moving", {"Banqiao": {"2022": 1000.0, "2023": 820.0}}),
        role=CandidateRole.TREND,
    )

    result = select_visualizations((candidate,))

    assert [spec.visualization_id for spec in result.selected] == ["moving"]
    assert result.rejected == ()


def test_the_strongest_series_decides_a_multi_series_line() -> None:
    candidate = VisualizationCandidate(
        spec=_line(
            "mixed",
            {
                "Banqiao": {"2022": 1000.0, "2023": 1001.0},
                "Pinglin": {"2022": 500.0, "2023": 300.0},
            },
        ),
        role=CandidateRole.TREND,
    )

    assert informativeness(candidate) == 1.0


def test_categories_within_noise_of_each_other_do_not_earn_a_bar_chart() -> None:
    candidate = VisualizationCandidate(
        spec=_bar("flat-bar", {"A": 100.0, "B": 101.0, "C": 100.5}),
        role=CandidateRole.CROSS_ENTITY,
    )

    result = select_visualizations((candidate,))

    assert result.selected == ()
    assert result.rejected[0].reason is RejectionReason.WEAK_SIGNAL


def test_a_bar_chart_with_real_contrast_survives() -> None:
    candidate = VisualizationCandidate(
        spec=_bar("real-bar", {"A": 100.0, "B": 60.0, "C": 20.0}),
        role=CandidateRole.CROSS_ENTITY,
    )

    assert select_visualizations((candidate,)).selected[0].visualization_id == "real-bar"


def test_changes_that_straddle_zero_are_measured_against_the_largest_magnitude() -> None:
    candidate = VisualizationCandidate(
        spec=_bar("signed", {"A": -400.0, "B": 500.0}),
        role=CandidateRole.CROSS_ENTITY,
    )

    assert informativeness(candidate) == 1.0


def test_only_one_view_per_role_reaches_the_answer() -> None:
    first = VisualizationCandidate(
        spec=_bar("comparison", {"A": 100.0, "B": 20.0}), role=CandidateRole.CROSS_ENTITY
    )
    second = VisualizationCandidate(
        spec=_bar("map", {"A": 100.0, "B": 30.0}), role=CandidateRole.CROSS_ENTITY
    )

    result = select_visualizations((first, second))

    assert len(result.selected) == 1
    assert result.rejected[0].reason is RejectionReason.REDUNDANT_VIEW


def test_a_trend_and_a_comparison_are_different_views_and_both_survive() -> None:
    trend = VisualizationCandidate(
        spec=_line("trend", {"Banqiao": {"2022": 1000.0, "2023": 800.0}}),
        role=CandidateRole.TREND,
    )
    comparison = VisualizationCandidate(
        spec=_bar("comparison", {"A": 100.0, "B": 20.0}), role=CandidateRole.CROSS_ENTITY
    )

    result = select_visualizations((trend, comparison))

    assert {spec.visualization_id for spec in result.selected} == {"trend", "comparison"}


def test_a_view_the_question_never_asked_for_is_rejected_on_intent() -> None:
    unwanted = VisualizationCandidate(
        spec=_bar("map", {"A": 100.0, "B": 20.0}),
        role=CandidateRole.CROSS_ENTITY,
        intent_fit=0.2,
    )

    result = select_visualizations((unwanted,))

    assert result.selected == ()
    assert result.rejected[0].reason is RejectionReason.WEAK_INTENT_FIT


def test_a_conflicting_result_blocks_every_chart_but_keeps_the_exact_table() -> None:
    profile = profile_series(
        _series(
            (
                ObservationPoint(
                    entity_id="banqiao", period="2023", value=100.0, estimated_value=0.0
                ),
                ObservationPoint(
                    entity_id="banqiao", period="2023", value=120.0, estimated_value=0.0
                ),
            )
        )
    )
    chart = VisualizationCandidate(
        spec=_bar("comparison", {"A": 100.0, "B": 20.0}), role=CandidateRole.CROSS_ENTITY
    )
    table = VisualizationCandidate(spec=_table("rows"), role=CandidateRole.AUDIT)

    result = select_visualizations((chart, table), profile=profile)

    assert [spec.visualization_id for spec in result.selected] == ["rows"]
    assert result.rejected[0].reason is RejectionReason.BLOCKING_ISSUE


def test_a_table_is_never_counted_against_the_chart_budget() -> None:
    trend = VisualizationCandidate(
        spec=_line("trend", {"Banqiao": {"2022": 1000.0, "2023": 800.0}}),
        role=CandidateRole.TREND,
    )
    comparison = VisualizationCandidate(
        spec=_bar("comparison", {"A": 100.0, "B": 20.0}), role=CandidateRole.CROSS_ENTITY
    )
    table = VisualizationCandidate(spec=_table("rows"), role=CandidateRole.AUDIT)

    result = select_visualizations((trend, comparison, table), chart_limit=2)

    assert [spec.visualization_id for spec in result.selected][-1] == "rows"
    assert len(result.selected) == 3


def test_the_chart_budget_rejects_the_weakest_surplus_view() -> None:
    strong = VisualizationCandidate(
        spec=_bar("strong", {"A": 100.0, "B": 10.0}), role=CandidateRole.CROSS_ENTITY
    )
    trend = VisualizationCandidate(
        spec=_line("trend", {"Banqiao": {"2022": 1000.0, "2023": 800.0}}),
        role=CandidateRole.TREND,
    )
    contribution = VisualizationCandidate(
        spec=_bar("contribution", {"A": 50.0, "B": 5.0}), role=CandidateRole.CONTRIBUTION
    )

    result = select_visualizations((strong, trend, contribution), chart_limit=2)

    assert len(result.selected) == 2
    assert result.rejected[0].reason is RejectionReason.OVER_LIMIT


def test_every_template_maps_to_a_default_role() -> None:
    assert role_for(VisualizationType.LINE) is CandidateRole.TREND
    assert role_for(VisualizationType.CHOROPLETH) is CandidateRole.CROSS_ENTITY
    assert role_for(VisualizationType.RANKING_BAR) is CandidateRole.CROSS_ENTITY
    assert role_for(VisualizationType.CONTRIBUTION_BAR) is CandidateRole.CONTRIBUTION
    assert role_for(VisualizationType.DATA_TABLE) is CandidateRole.AUDIT
