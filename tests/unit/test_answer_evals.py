"""End-to-end answer grading, doc 30 stage 6.

The suite grades synthetic responses so each dimension is exercised in
isolation; `tests/integration/test_answer_eval_suite.py` runs the real agent.
"""

import asyncio
from datetime import UTC, datetime

from youth_compass.agent.answer_evals import (
    AnswerDimension,
    AnswerEvalCase,
    AnswerEvalHarness,
    grade_answer,
)
from youth_compass.agent.contracts import (
    CopilotResponse,
    CopilotStatus,
    DataFreshness,
    DataLimitations,
    EntityChange,
    EntityComparison,
    EvidenceCitation,
    EvidenceExcerptRow,
    ObservationPoint,
    ObservationSeries,
    ToolTrace,
    VisualizationSpec,
    VisualizationType,
)

NOW = datetime(2026, 9, 13, tzinfo=UTC)


def _citation() -> EvidenceCitation:
    return EvidenceCitation(
        citation_id="data-1",
        dataset_id="population",
        dataset_version="v1",
        quality_score=1.0,
        retrieved_at=NOW,
        excerpt=(
            EvidenceExcerptRow(
                entity_id="banqiao",
                entity_name="Banqiao",
                metric_code="population_count",
                metric_name="Population count",
                value=170215,
                period="2011-01",
            ),
            EvidenceExcerptRow(
                entity_id="banqiao",
                entity_name="Banqiao",
                metric_code="population_count",
                metric_name="Population count",
                value=106473,
                period="2026-07",
            ),
        ),
    )


def _limitations() -> DataLimitations:
    return DataLimitations(
        freshness=(
            DataFreshness(
                citation_id="data-1",
                dataset_id="population",
                dataset_version="v1",
                published_at=NOW,
                age_days=0,
            ),
        )
    )


def _series() -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(
                entity_id="banqiao", period="2011-01", value=170215, estimated_value=0
            ),
            ObservationPoint(
                entity_id="banqiao", period="2026-07", value=106473, estimated_value=0
            ),
        ),
    )


def _comparison() -> EntityComparison:
    return EntityComparison(
        metric_code="population_count",
        unit_code="persons",
        changes=(
            EntityChange(
                entity_id="banqiao",
                entity_name="Banqiao",
                first_period="2011-01",
                last_period="2026-07",
                first_value=170215,
                last_value=106473,
                absolute_change=-63742,
                percent_change=-37.45,
                direction="decreased",
                observation_count=2,
            ),
        ),
    )


def _response(**overrides: object) -> CopilotResponse:
    base: dict[str, object] = {
        "status": CopilotStatus.ANSWERED,
        "answer": (
            "Banqiao's youth population fell from 170,215 in 2011-01 to "
            "106,473 in 2026-07—a decline of 37.45%. [data-1]"
        ),
        "generated_at": NOW,
        "observation_series": _series(),
        "comparison": _comparison(),
        "citations": (_citation(),),
        "limitations": _limitations(),
        "tool_trace": (
            ToolTrace(tool="query_observations", outcome="ok", summary="retrieved 2 rows"),
        ),
    }
    base.update(overrides)
    return CopilotResponse.model_validate(base)


def _case(**overrides: object) -> AnswerEvalCase:
    base: dict[str, object] = {
        "case_id": "banqiao-trend",
        "question": "What is the youth population trend in Banqiao?",
        "expect_datasets": ("population",),
    }
    base.update(overrides)
    return AnswerEvalCase.model_validate(base)


def _score(case: AnswerEvalCase, response: CopilotResponse, dimension: AnswerDimension) -> float:
    result = grade_answer(case, response)
    return next(item.score for item in result.scores if item.dimension is dimension)


def test_a_fully_grounded_answer_passes_every_dimension() -> None:
    result = grade_answer(_case(), _response())

    assert result.passed, result.failures
    assert {item.dimension for item in result.scores} == set(AnswerDimension)


def test_a_number_absent_from_the_evidence_fails_grounding() -> None:
    response = _response(answer="Banqiao's youth population fell to 99,999 by 2026-07. [data-1]")

    assert _score(_case(), response, AnswerDimension.GROUNDING) == 0.0
    assert "99999" in grade_answer(_case(), response).failures[0]


def test_a_rounded_figure_is_allowed_but_an_invented_one_is_not() -> None:
    rounded = _response(answer="Banqiao's youth population fell 37.5% by 2026-07. [data-1]")
    invented = _response(answer="Banqiao's youth population fell 37.9% by 2026-07. [data-1]")

    assert _score(_case(), rounded, AnswerDimension.GROUNDING) == 1.0
    assert _score(_case(), invented, AnswerDimension.GROUNDING) == 0.0


def test_a_citation_id_is_not_read_as_a_number() -> None:
    # "data-1" must not contribute a 1 that the grounding check then demands.
    assert _score(_case(), _response(), AnswerDimension.GROUNDING) == 1.0


def test_an_unattached_citation_reference_fails() -> None:
    response = _response(answer="Banqiao fell to 106,473 in 2026-07. [data-7]")

    assert _score(_case(), response, AnswerDimension.CITATION) == 0.0


def test_evidence_that_the_answer_never_points_to_fails() -> None:
    response = _response(answer="Banqiao fell to 106,473 in 2026-07.")

    assert _score(_case(), response, AnswerDimension.CITATION) == 0.0


def test_a_missing_expected_dataset_fails_citation() -> None:
    case = _case(expect_datasets=("population", "employment"))

    assert _score(case, _response(), AnswerDimension.CITATION) == 0.0


def test_an_answer_in_the_wrong_language_fails() -> None:
    case = _case(question="Dân số thanh niên Bản Kiều thay đổi thế nào?")
    chinese = _response(answer="板橋區的青年人口下降至106,473人。[data-1]")

    assert _score(case, chinese, AnswerDimension.LANGUAGE) == 0.0


def test_an_answer_matching_the_questions_language_passes() -> None:
    case = _case(question="Dân số thanh niên Bản Kiều thay đổi thế nào?")
    vietnamese = _response(
        answer="Dân số thanh niên Bản Kiều giảm còn 106,473 người vào 2026-07. [data-1]"
    )

    assert _score(case, vietnamese, AnswerDimension.LANGUAGE) == 1.0


def test_an_answered_turn_without_a_freshness_audit_fails() -> None:
    assert _score(_case(), _response(limitations=None), AnswerDimension.LIMITATIONS) == 0.0


def test_a_refusal_needs_no_limitation_block() -> None:
    case = _case(expect_status=CopilotStatus.UNSUPPORTED_QUESTION, expect_datasets=())
    response = _response(
        status=CopilotStatus.UNSUPPORTED_QUESTION,
        answer="What metric, geography, time period, or decision should be analyzed?",
        citations=(),
        comparison=None,
        observation_series=None,
        limitations=None,
    )
    result = grade_answer(case, response)

    assert result.passed, result.failures


def test_the_wrong_status_fails_even_when_the_prose_is_fine() -> None:
    case = _case(expect_status=CopilotStatus.INSUFFICIENT_DATA)

    assert _score(case, _response(), AnswerDimension.STATUS) == 0.0


def test_a_tool_the_case_requires_must_appear_on_the_trace() -> None:
    case = _case(expect_tools=("query_observations", "audit_limitations"))

    assert _score(case, _response(), AnswerDimension.TOOL_TRACE) == 0.0


def test_an_expected_chart_that_is_missing_fails() -> None:
    case = _case(expect_visualization=VisualizationType.LINE)

    assert _score(case, _response(), AnswerDimension.VISUALIZATION) == 0.0


def test_a_case_expecting_no_chart_fails_when_one_is_drawn() -> None:
    case = _case(expect_no_chart=True)
    response = _response(
        visualizations=(
            VisualizationSpec(
                visualization_id="observation-trend",
                type=VisualizationType.LINE,
                title="Trend",
                x={"field": "period", "label": "Period", "data_type": "temporal"},
                y={"field": "value", "label": "Value", "data_type": "quantitative"},
                rows=({"period": "2026-07", "value": 106473.0},),
            ),
        )
    )

    assert _score(case, response, AnswerDimension.VISUALIZATION) == 0.0


def test_an_audit_table_does_not_count_as_a_chart() -> None:
    case = _case(expect_no_chart=True)
    response = _response(
        visualizations=(
            VisualizationSpec(
                visualization_id="rows",
                type=VisualizationType.DATA_TABLE,
                title="Rows",
                columns=({"field": "value", "label": "Value", "unit": None},),
                rows=({"value": 106473.0},),
            ),
        )
    )

    assert _score(case, response, AnswerDimension.VISUALIZATION) == 1.0


def test_forbidden_text_reaching_the_reader_fails_disclosure() -> None:
    case = _case(forbidden_substrings=("demo_", "s3://"))
    response = _response(answer="Scored from demo_transit_accessibility. [data-1]")

    assert _score(case, response, AnswerDimension.DISCLOSURE) == 0.0


def test_a_chart_headline_is_checked_for_forbidden_text_too() -> None:
    case = _case(forbidden_substrings=("demo_",))
    response = _response(
        visualizations=(
            VisualizationSpec(
                visualization_id="observation-trend",
                type=VisualizationType.LINE,
                title="Trend",
                headline="demo_transit_accessibility leads",
                x={"field": "period", "label": "Period", "data_type": "temporal"},
                y={"field": "value", "label": "Value", "data_type": "quantitative"},
                rows=({"period": "2026-07", "value": 106473.0},),
            ),
        )
    )

    assert _score(case, response, AnswerDimension.DISCLOSURE) == 0.0


class _Crashing:
    async def answer(self, question: str, **kwargs: object) -> CopilotResponse:
        raise RuntimeError("query engine unavailable")


class _Stub:
    async def answer(self, question: str, **kwargs: object) -> CopilotResponse:
        return _response()


def test_a_crash_is_a_failed_case_not_a_failed_run() -> None:
    report = asyncio.run(AnswerEvalHarness(_Crashing()).run([_case(), _case(case_id="second")]))

    assert report.total == 2
    assert report.failed == 2
    assert report.results[0].error is not None
    assert "query engine unavailable" in report.results[0].error


def test_the_report_names_which_dimensions_broke_across_the_suite() -> None:
    harness = AnswerEvalHarness(_Stub())
    report = asyncio.run(
        harness.run(
            [_case(), _case(case_id="wrong-status", expect_status=CopilotStatus.INSUFFICIENT_DATA)]
        )
    )

    assert report.passed == 1
    assert report.pass_rate == 0.5
    assert report.failing_dimensions == ("status",)
