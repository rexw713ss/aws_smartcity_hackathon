"""A rubric for the chart an answer chose. Doc 30, stage 6.

Adapted from the `VizEvaluator` of microsoft/lida, minus the two dimensions that
do not apply here: this system generates no code, so there are no bugs to find,
and the frontend owns style, so aesthetics are not the backend's to score. What
remains is scored deterministically from the spec and the profile of the rows it
was built from, which keeps the rubric usable in CI without a model in the loop.

"No chart" is a gradeable outcome. A case that declares a result too flat or too
broken to plot passes only when the agent actually declined to plot it.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import VisualizationSpec, VisualizationType
from youth_compass.agent.data_shape import SeriesProfile
from youth_compass.agent.measures import Measure, Transform
from youth_compass.agent.viz_selection import (
    CandidateRole,
    VisualizationCandidate,
    informativeness,
    role_for,
)

_PASS = 1.0
_FAIL = 0.0
_MIN_PERIODS_FOR_LINE = 2
_SLOPE_PERIODS = 2
_MIN_BAR_CATEGORIES = 2


class RubricDimension(StrEnum):
    """What a chart is judged on."""

    GOAL_COMPLIANCE = "goal_compliance"
    VISUALIZATION_TYPE = "visualization_type"
    DATA_ENCODING = "data_encoding"
    UNIT_APPROPRIATENESS = "unit_appropriateness"
    INSIGHT_STRENGTH = "insight_strength"


class VisualizationEvalCase(BaseModel):
    """What one question should produce, declared before the agent runs."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    question: str = Field(min_length=3)
    # None means "any defensible chart"; pair it with expect_no_chart to require
    # that the agent declines instead.
    expected_type: VisualizationType | None = None
    expect_no_chart: bool = False
    expected_transform: Transform | None = None
    min_informativeness: float = Field(default=0.4, ge=0.0, le=1.0)
    require_headline: bool = True


class DimensionScore(BaseModel):
    """One dimension's verdict, with the reason it was given."""

    model_config = ConfigDict(frozen=True)

    dimension: RubricDimension
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class VisualizationEvalResult(BaseModel):
    """The graded outcome for one case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    scores: tuple[DimensionScore, ...]

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{item.dimension.value}: {item.rationale}"
            for item in self.scores
            if item.score < _PASS
        )


def grade_visualizations(
    case: VisualizationEvalCase,
    specs: tuple[VisualizationSpec, ...],
    *,
    profile: SeriesProfile,
    measure: Measure | None = None,
) -> VisualizationEvalResult:
    """Score what the agent produced against what the case declared."""

    charts = tuple(spec for spec in specs if role_for(spec.type) is not CandidateRole.AUDIT)
    if case.expect_no_chart:
        declined = not charts
        return VisualizationEvalResult(
            case_id=case.case_id,
            passed=declined,
            scores=(
                DimensionScore(
                    dimension=RubricDimension.GOAL_COMPLIANCE,
                    score=_PASS if declined else _FAIL,
                    rationale=(
                        "declined to plot a result that cannot carry a chart"
                        if declined
                        else f"plotted {len(charts)} chart(s) from a result that should carry none"
                    ),
                ),
            ),
        )
    if not charts:
        return VisualizationEvalResult(
            case_id=case.case_id,
            passed=False,
            scores=(
                DimensionScore(
                    dimension=RubricDimension.GOAL_COMPLIANCE,
                    score=_FAIL,
                    rationale="the question expected a chart and none was produced",
                ),
            ),
        )
    chart = _primary(charts, case.expected_type)
    scores = (
        _goal_compliance(case, chart),
        _visualization_type(chart, profile),
        _data_encoding(chart, profile),
        _unit_appropriateness(case, chart, measure),
        _insight_strength(case, chart),
    )
    return VisualizationEvalResult(
        case_id=case.case_id,
        passed=all(item.score >= _PASS for item in scores),
        scores=scores,
    )


def _primary(
    charts: tuple[VisualizationSpec, ...], expected: VisualizationType | None
) -> VisualizationSpec:
    """Grade the chart the case is about, not whichever one happens to be first."""

    if expected is None:
        return charts[0]
    return next((chart for chart in charts if chart.type is expected), charts[0])


def _goal_compliance(case: VisualizationEvalCase, chart: VisualizationSpec) -> DimensionScore:
    if case.expected_type is not None and chart.type is not case.expected_type:
        return DimensionScore(
            dimension=RubricDimension.GOAL_COMPLIANCE,
            score=_FAIL,
            rationale=f"expected a {case.expected_type.value}, produced a {chart.type.value}",
        )
    if case.require_headline and not chart.headline:
        return DimensionScore(
            dimension=RubricDimension.GOAL_COMPLIANCE,
            score=_FAIL,
            rationale="the chart states no finding, only a subject",
        )
    return DimensionScore(
        dimension=RubricDimension.GOAL_COMPLIANCE,
        score=_PASS,
        rationale="the chart answers the question that was asked",
    )


def _visualization_type(chart: VisualizationSpec, profile: SeriesProfile) -> DimensionScore:
    """Is this template honest for this data shape?"""

    reason: str | None = None
    match chart.type:
        case VisualizationType.LINE:
            if profile.period_count < _MIN_PERIODS_FOR_LINE:
                reason = "a line needs at least two periods"
        case VisualizationType.SLOPE:
            if profile.period_count != _SLOPE_PERIODS:
                reason = "a slope reads exactly two periods"
        case VisualizationType.CHOROPLETH:
            if chart.region_field is None or chart.region_scheme is None:
                reason = "a map must name its region key and boundary scheme"
        case VisualizationType.COMPARISON_BAR | VisualizationType.RANKING_BAR:
            if len(chart.rows) < _MIN_BAR_CATEGORIES:
                reason = "a bar chart of one category is a number"
        case _:
            reason = None
    return DimensionScore(
        dimension=RubricDimension.VISUALIZATION_TYPE,
        score=_FAIL if reason else _PASS,
        rationale=reason or f"{chart.type.value} suits this data shape",
    )


def _data_encoding(chart: VisualizationSpec, profile: SeriesProfile) -> DimensionScore:
    if chart.x is None or chart.y is None:
        return DimensionScore(
            dimension=RubricDimension.DATA_ENCODING,
            score=_FAIL,
            rationale="a chart must declare both axes",
        )
    if chart.y.data_type != "quantitative":
        return DimensionScore(
            dimension=RubricDimension.DATA_ENCODING,
            score=_FAIL,
            rationale="the measured axis must be quantitative",
        )
    if (
        role_for(chart.type) is CandidateRole.TREND
        and profile.entity_count > 1
        and chart.series_field is None
    ):
        return DimensionScore(
            dimension=RubricDimension.DATA_ENCODING,
            score=_FAIL,
            rationale="several entities share one line with no series field to separate them",
        )
    return DimensionScore(
        dimension=RubricDimension.DATA_ENCODING,
        score=_PASS,
        rationale="fields sit on the channels their data types call for",
    )


def _unit_appropriateness(
    case: VisualizationEvalCase, chart: VisualizationSpec, measure: Measure | None
) -> DimensionScore:
    if case.expected_transform is not None and (
        measure is None or measure.transform is not case.expected_transform
    ):
        found = measure.transform.value if measure else "none"
        return DimensionScore(
            dimension=RubricDimension.UNIT_APPROPRIATENESS,
            score=_FAIL,
            rationale=f"expected the {case.expected_transform.value} measure, chose {found}",
        )
    if chart.y is not None and chart.y.unit is None:
        return DimensionScore(
            dimension=RubricDimension.UNIT_APPROPRIATENESS,
            score=_FAIL,
            rationale="the measured axis carries no unit, so its numbers cannot be read",
        )
    return DimensionScore(
        dimension=RubricDimension.UNIT_APPROPRIATENESS,
        score=_PASS,
        rationale="the measure makes the comparison legible",
    )


def _insight_strength(case: VisualizationEvalCase, chart: VisualizationSpec) -> DimensionScore:
    strength = informativeness(VisualizationCandidate(spec=chart, role=role_for(chart.type)))
    passed = strength >= case.min_informativeness
    return DimensionScore(
        dimension=RubricDimension.INSIGHT_STRENGTH,
        score=_PASS if passed else _FAIL,
        rationale=(
            f"signal {strength:.2f} clears the {case.min_informativeness:.2f} floor"
            if passed
            else f"signal {strength:.2f} is below the {case.min_informativeness:.2f} floor"
        ),
    )


__all__ = [
    "DimensionScore",
    "RubricDimension",
    "VisualizationEvalCase",
    "VisualizationEvalResult",
    "grade_visualizations",
]
