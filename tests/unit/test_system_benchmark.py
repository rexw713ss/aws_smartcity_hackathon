import asyncio
from datetime import UTC, datetime

import pytest

from youth_compass.agent.answer_evals import AnswerEvalCase
from youth_compass.agent.benchmarking import BenchmarkPricing, run_benchmark
from youth_compass.agent.contracts import CopilotResponse, CopilotStatus, ToolTrace


class _MeasuredService:
    async def answer(
        self,
        question: str,
        *,
        entity_ids: tuple[str, ...] = (),
        min_quality_score: float = 0.0,
    ) -> CopilotResponse:
        del question, entity_ids, min_quality_score
        return CopilotResponse(
            status=CopilotStatus.UNSUPPORTED_QUESTION,
            answer="Please clarify the analysis goal.",
            generated_at=datetime.now(UTC),
            tool_trace=(
                ToolTrace(
                    tool="query_decomposer",
                    outcome="clarification",
                    summary="planned by keyword_table",
                    duration_ms=2,
                ),
                ToolTrace(
                    tool="query_observations",
                    outcome="ok",
                    summary="one small scan",
                    duration_ms=4,
                    scanned_bytes=1024**2,
                ),
            ),
            warnings=("No data tool was executed before clarification.",),
        )


def test_benchmark_aggregates_latency_quality_scan_and_athena_minimum() -> None:
    case = AnswerEvalCase(
        case_id="clarify",
        question="Tell me something useful",
        expect_status=CopilotStatus.UNSUPPORTED_QUESTION,
        require_limitations=False,
        expect_no_chart=True,
    )
    report = asyncio.run(
        run_benchmark(
            _MeasuredService(),
            [case],
            iterations=2,
            warmup=1,
            pricing=BenchmarkPricing(athena_usd_per_tb=5),
        )
    )

    assert report.measured_requests == 2
    assert report.warmup_requests == 1
    assert report.successful_requests == 2
    assert report.error_rate == 0
    assert report.total_scanned_bytes == 2 * 1024**2
    assert report.total_projected_billable_bytes == 20_000_000
    assert report.projected_total_variable_cost_usd == pytest.approx(20_000_000 / 10**12 * 5)
    assert report.latency is not None
    assert report.latency.p95_ms >= report.latency.p50_ms
    assert {item.tool for item in report.tools} == {
        "query_decomposer",
        "query_observations",
    }


def test_zero_byte_cache_hit_has_no_projected_athena_charge() -> None:
    class _CachedService(_MeasuredService):
        async def answer(self, *args: object, **kwargs: object) -> CopilotResponse:
            response = await super().answer("question")
            cached = response.tool_trace[1].model_copy(update={"scanned_bytes": 0})
            return response.model_copy(update={"tool_trace": (cached,)})

    case = AnswerEvalCase(
        case_id="cached",
        question="Tell me something useful",
        expect_status=CopilotStatus.UNSUPPORTED_QUESTION,
        require_limitations=False,
    )
    report = asyncio.run(run_benchmark(_CachedService(), [case]))

    assert report.samples[0].query_count == 1
    assert report.samples[0].billable_query_count == 0
    assert report.total_projected_billable_bytes == 0
    assert report.projected_athena_cost_usd == 0


def test_benchmark_leaves_model_cost_unknown_without_usage() -> None:
    class _ModelService(_MeasuredService):
        async def answer(self, *args: object, **kwargs: object) -> CopilotResponse:
            response = await super().answer("question")
            return response.model_copy(
                update={
                    "tool_trace": (
                        ToolTrace(
                            tool="answer_composer",
                            outcome="model",
                            summary="model composition",
                            duration_ms=1,
                        ),
                    )
                }
            )

    case = AnswerEvalCase(
        case_id="model",
        question="Tell me something useful",
        expect_status=CopilotStatus.UNSUPPORTED_QUESTION,
        require_limitations=False,
    )
    report = asyncio.run(
        run_benchmark(
            _ModelService(),
            [case],
            pricing=BenchmarkPricing(
                model_input_usd_per_million_tokens=1,
                model_output_usd_per_million_tokens=2,
            ),
        )
    )

    assert report.samples[0].model_invocation_count == 1
    assert not report.samples[0].model_usage_complete
    assert report.projected_model_cost_usd is None
    assert report.projected_total_variable_cost_usd is None
