"""A cohort forecast answer states its drivers and its evidence, and stays grounded."""

from datetime import UTC, datetime

from youth_compass.agent.answer_evals import AnswerDimension, AnswerEvalCase, grade_answer
from youth_compass.agent.contracts import CopilotResponse, CopilotStatus, VisualizationType
from youth_compass.agent.observation_answering import (
    _forecast_accuracy_answer,
    _forecast_answer,
    _forecast_assumptions,
    _forecast_warnings,
)
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.ports import (
    CandidateEvaluation,
    ForecastAccuracy,
    ForecastComponents,
    ForecastEvaluation,
    ForecastPoint,
    ForecastResult,
)

_GENERATED = datetime(2026, 9, 13, tzinfo=UTC)


def _accuracy(mape: float) -> list[ForecastAccuracy]:
    return [
        ForecastAccuracy(
            horizon_years=horizon,
            samples=200,
            mape_percent=mape * horizon,
            p90_ape_percent=mape * horizon * 2,
            bias_percent=0.3,
            interval_coverage=0.85,
        )
        for horizon in (1, 2)
    ]


def _result(*districts: tuple[str, bool]) -> ForecastResult:
    points = [
        ForecastPoint(
            district_code=code,
            year_gregorian=year,
            value=value,
            lower=value - 500,
            upper=value + 400,
            components=ForecastComponents(
                base_period="2026-07",
                base_value=27645,
                entering=entering,
                ageing_out=ageing_out,
                net_change=value - (27645 + entering - ageing_out),
            ),
            small_area=small,
        )
        for code, small in districts
        for year, value, entering, ageing_out in (
            (2027, 27800.0, 1500.0, 1900.0),
            (2028, 28376.0, 3100.0, 3800.0),
        )
    ]
    return ForecastResult(
        metric_code="population_count",
        model_version="cohort-change-ratio-v1",
        points=points,
        generated_at=_GENERATED,
        evaluation=ForecastEvaluation(
            method="Hamilton-Perry cohort change ratios",
            selected_model="cohort-change-ratio-v1",
            baseline_model="naive-last-value",
            base_period="2026-07",
            target_coverage=0.8,
            error_quantile=0.9,
            rolling_coverage=0.855,
            rolling_samples=899,
            small_area_coverage=0.823,
            candidates=[
                CandidateEvaluation(model="cohort-change-ratio-v1", accuracy=_accuracy(0.8)),
                CandidateEvaluation(model="naive-last-value", accuracy=_accuracy(2.4)),
            ],
        ),
    )


def test_the_fallback_answer_names_drivers_and_backtest_accuracy() -> None:
    answer = _forecast_answer(_result(("17", False)))

    assert "28,376" in answer
    assert "3,100 people reach 18" in answer
    assert "3,800 pass 35" in answer
    assert "2-year horizon" in answer
    assert "1.6% on average" in answer
    assert "4.8% for the naive baseline" in answer


def test_small_districts_and_the_meaning_of_net_change_are_warned() -> None:
    warnings = _forecast_warnings(_result(("23", True), ("17", False)))

    assert any("fewer than 10,000 residents" in item and "Shimen" in item for item in warnings)
    assert any("not migration alone" in item for item in warnings)


def test_assumptions_state_the_method_and_held_out_coverage() -> None:
    assumptions = _forecast_assumptions(_result(("17", False)))

    assert any("Hamilton-Perry" in item for item in assumptions)
    assert any("90% quantile of past absolute backtest errors" in item for item in assumptions)
    assert any(
        "contained 86% of 899 past outcomes (82% in districts" in item for item in assumptions
    )


def test_one_district_gets_a_signed_driver_chart() -> None:
    specs = VisualizationBuilder().forecast("Forecast Linkou", _result(("17", False)), ("data-1",))
    drivers = next(item for item in specs if item.visualization_id == "forecast-drivers")

    assert drivers.type is VisualizationType.CONTRIBUTION_BAR
    assert [row["persons"] for row in drivers.rows] == [3100.0, -3800.0, 1431.0]


def test_several_districts_get_a_driver_table_in_the_question_language() -> None:
    specs = VisualizationBuilder().forecast(
        "預測青年人口", _result(("17", False), ("01", False)), ("data-1",)
    )
    table = next(item for item in specs if item.visualization_id == "forecast-drivers-table")

    assert table.type is VisualizationType.DATA_TABLE
    assert len(table.rows) == 2
    assert [column.label for column in table.columns][2:5] == [
        "年滿18歲",
        "超過35歲",
        "年齡推移外淨變動",
    ]


def test_the_grader_accepts_every_figure_the_forecast_answer_states() -> None:
    result = _result(("17", False))
    response = CopilotResponse(
        status=CopilotStatus.ANSWERED,
        answer=_forecast_answer(result),
        generated_at=_GENERATED,
        forecast_result=result,
    )
    case = AnswerEvalCase(case_id="forecast", question="Forecast Linkou")

    grounding = next(
        item
        for item in grade_answer(case, response).scores
        if item.dimension is AnswerDimension.GROUNDING
    )

    assert grounding.score == 1.0, grounding.rationale


def test_an_accuracy_question_leads_with_every_backtested_horizon() -> None:
    answer = _forecast_accuracy_answer(_result(("17", False)))

    assert answer is not None
    assert "beat naive-last-value at every backtested horizon" in answer
    assert "At 1 year it missed by 0.8% on average over 200 district forecasts" in answer
    assert "district forecasts (naive baseline 2.4%)" in answer
    assert "its interval contained 85% of outcomes" in answer
    assert "Intervals target 80% coverage" in answer


def test_undercovering_intervals_are_warned() -> None:
    result = _result(("17", False))
    assert result.evaluation is not None
    result.evaluation.rolling_coverage = 0.64

    warnings = _forecast_warnings(result)

    assert any("only 64% of past outcomes, below the 80% target" in item for item in warnings)


def test_the_grader_accepts_the_accuracy_answer() -> None:
    result = _result(("17", False))
    response = CopilotResponse(
        status=CopilotStatus.ANSWERED,
        answer=_forecast_accuracy_answer(result) or "",
        generated_at=_GENERATED,
        forecast_result=result,
    )
    case = AnswerEvalCase(case_id="accuracy", question="How accurate is the forecast?")

    grounding = next(
        item
        for item in grade_answer(case, response).scores
        if item.dimension is AnswerDimension.GROUNDING
    )

    assert grounding.score == 1.0, grounding.rationale
