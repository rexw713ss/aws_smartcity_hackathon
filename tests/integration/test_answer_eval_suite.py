"""The answer eval suite, run against the real agent over the repo data root.

This is the regression guard for what a user actually reads. It runs the same
cases `scripts/run_agent_evals.py --suite answers` runs, so a change that breaks
an answer fails here rather than in a demo.
"""

import asyncio
from pathlib import Path

import pytest

from apps.api.dependencies import LocalRuntime
from youth_compass.agent import (
    AnswerEvalHarness,
    AnswerEvalReport,
    load_answer_eval_cases,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "agent-answers.jsonl"
DATA_ROOT = ROOT / "data"


@pytest.fixture(scope="module")
def report() -> AnswerEvalReport:
    if not (DATA_ROOT / "metadata" / "youth-compass.sqlite3").exists():
        pytest.skip("no local catalog; run the ingestion workflow first")
    runtime = LocalRuntime(DATA_ROOT)
    return asyncio.run(AnswerEvalHarness(runtime.copilot()).run(load_answer_eval_cases(CASES)))


def test_the_suite_has_cases_and_every_one_produced_a_verdict(
    report: AnswerEvalReport,
) -> None:
    assert report.total == len(load_answer_eval_cases(CASES))
    assert all(result.error is None for result in report.results), [
        result.error for result in report.results if result.error
    ]


def test_every_case_passes(report: AnswerEvalReport) -> None:
    failures = {result.case_id: result.failures for result in report.results if not result.passed}

    assert not failures, failures


def test_an_unpublished_metric_is_refused_rather_than_substituted(
    report: AnswerEvalReport,
) -> None:
    """Asking for a metric the catalog lacks must produce a gap, not a stand-in.

    This was a live bug: "youth unemployment by district" returned population
    counts with status answered and citations attached, and nothing in the
    response said the metric had been swapped. The metric selector short-circuited
    whenever a dataset published exactly one metric, so relevance was never
    tested. It now refuses, names what is missing against what exists, and puts
    the requested metric on `data_requirement` so acquisition can close the gap.
    """

    result = next(
        item for item in report.results if item.case_id == "refuses-an-unpublished-metric"
    )

    assert result.passed, result.failures
