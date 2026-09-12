"""Evaluation dataset loading and exact decomposition/router scoring."""

import asyncio
from pathlib import Path

from youth_compass.agent import (
    AgentEvalCase,
    AgentEvalHarness,
    AnalysisOperation,
    DeterministicQueryDecomposer,
    SmartToolRouter,
    default_decision_capabilities,
    load_eval_cases,
    register_forecast_capabilities,
    register_observation_capabilities,
)


def _harness() -> AgentEvalHarness:
    capabilities = default_decision_capabilities()
    register_observation_capabilities(capabilities)
    register_forecast_capabilities(capabilities)
    return AgentEvalHarness(DeterministicQueryDecomposer(), SmartToolRouter(capabilities))


def test_bundled_agent_eval_suite_passes_offline() -> None:
    cases = load_eval_cases(Path("evals/agent-routing.jsonl"))

    assert sum(case.case_id.startswith("zh-hant-") for case in cases) == 6
    assert sum(case.case_id.startswith("en-") for case in cases) == 6

    report = asyncio.run(_harness().run(cases))

    assert report.total == 12
    assert report.passed == 12
    assert report.failed == 0
    assert report.pass_rate == 1.0


def test_eval_report_explains_semantic_mismatch() -> None:
    case = AgentEvalCase(
        case_id="intentional-mismatch",
        question="Compare population trend",
        expected_operations=(AnalysisOperation.SEARCH_CATALOG,),
        expected_tools=("search_catalog",),
    )

    report = asyncio.run(_harness().run((case,)))

    assert report.failed == 1
    assert report.results[0].passed is False
    assert any("operations" in failure for failure in report.results[0].failures)
