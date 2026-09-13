"""End-to-end grading of one grounded turn. Doc 30 stage 6, widened to the answer.

`agent.evals` grades the plan: did the question decompose into the right
operations and route to the right tools. That says nothing about what the user
finally reads. This module grades the turn a user actually gets — its status,
its numbers, its citations, its language, its caveats, and its charts — from the
`CopilotResponse` alone, with no model in the loop, so it runs in CI.

The dimension that matters most is GROUNDING. `answering.ModelAnswerComposer`
already refuses a draft whose numbers are not copied from the facts it was
given; this re-derives the allowed set independently, from the evidence the
response itself carries, and checks the text that was actually returned. A
single implementation checking its own work proves nothing. Two independent
ones disagreeing is a bug report, and this one also covers the deterministic
fallback templates, which the composer's guard never sees.
"""

import json
import re
from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import (
    CopilotResponse,
    CopilotStatus,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.viz_selection import CandidateRole, role_for
from youth_compass.forecasting.cohort import YOUTH_MAX_AGE, YOUTH_MIN_AGE
from youth_compass.forecasting.evaluation import SMALL_AREA_POPULATION
from youth_compass.ontology import NameLanguage, question_language

_PASS = 1.0
_FAIL = 0.0
# Matches an integer or decimal, with or without thousands separators, but not
# the digits inside an identifier such as `data-1`. The guard is ASCII-only on
# purpose: `\w` treats a Han character as a word character, so a Chinese answer
# writing 的170,215人 would have its leading digits swallowed and the remainder
# read as a separate, ungrounded 215.
_NUMBER = re.compile(
    r"(?<![0-9A-Za-z_.-])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![0-9A-Za-z_.-])\d+(?:\.\d+)?"
)
_CITATION = re.compile(r"\bdata-\d+\b")
_PERIOD = re.compile(r"\b\d{4}(?:-\d{2})?\b")
_HAN = re.compile(r"[一-鿿]")
_VIETNAMESE = re.compile(
    r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]"
)


class AnswerDimension(StrEnum):
    """What one turn is judged on."""

    STATUS = "status"
    GROUNDING = "grounding"
    CITATION = "citation"
    LANGUAGE = "language"
    LIMITATIONS = "limitations"
    TOOL_TRACE = "tool_trace"
    VISUALIZATION = "visualization"
    DISCLOSURE = "disclosure"


class AnswerEvalCase(BaseModel):
    """What one question must produce, declared before the agent runs."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    question: str = Field(min_length=3)
    entity_ids: tuple[str, ...] = ()
    min_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    expect_status: CopilotStatus = CopilotStatus.ANSWERED
    # Datasets the answer must cite. A refusal case leaves this empty.
    expect_datasets: tuple[str, ...] = ()
    expect_tools: tuple[str, ...] = ()
    expect_language: NameLanguage | None = None
    expect_visualization: VisualizationType | None = None
    expect_no_chart: bool = False
    require_limitations: bool = True
    # Substrings that must never reach the user: internal identifiers, storage
    # paths, or the demo-feature prefix presented as if it were published data.
    forbidden_substrings: tuple[str, ...] = ()


class DimensionScore(BaseModel):
    """One dimension's verdict and the reason for it."""

    model_config = ConfigDict(frozen=True)

    dimension: AnswerDimension
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class AnswerEvalResult(BaseModel):
    """The graded outcome of one case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    status: CopilotStatus | None = None
    scores: tuple[DimensionScore, ...] = ()
    # Set when the agent raised instead of answering, so a crash is a failed
    # case rather than an aborted run.
    error: str | None = None

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{item.dimension.value}: {item.rationale}"
            for item in self.scores
            if item.score < _PASS
        )


class AnswerEvalReport(BaseModel):
    """Aggregate suitable for CI output."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    results: tuple[AnswerEvalResult, ...] = ()

    @property
    def failing_dimensions(self) -> tuple[str, ...]:
        """Which dimensions broke, across the whole suite, most common first."""

        counts: dict[str, int] = {}
        for result in self.results:
            for item in result.scores:
                if item.score < _PASS:
                    counts[item.dimension.value] = counts.get(item.dimension.value, 0) + 1
        return tuple(name for name, _ in sorted(counts.items(), key=lambda kv: -kv[1]))


def grade_answer(case: AnswerEvalCase, response: CopilotResponse) -> AnswerEvalResult:
    """Score one response against its case, without re-running anything."""

    scores = [
        _status(case, response),
        _grounding(response),
        _citation(case, response),
        _language(case, response),
        _limitations(case, response),
        _tool_trace(case, response),
        _visualization(case, response),
        _disclosure(case, response),
    ]
    return AnswerEvalResult(
        case_id=case.case_id,
        passed=all(item.score >= _PASS for item in scores),
        status=response.status,
        scores=tuple(scores),
    )


class AnswerEvalHarness:
    """Run cases through a real agent and grade what comes back."""

    def __init__(self, service: "_AnswerService") -> None:
        self._service = service

    async def run(self, cases: Sequence[AnswerEvalCase]) -> AnswerEvalReport:
        results: list[AnswerEvalResult] = []
        for case in cases:
            results.append(await self._run_one(case))
        passed = sum(result.passed for result in results)
        total = len(results)
        return AnswerEvalReport(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total else 1.0,
            results=tuple(results),
        )

    async def _run_one(self, case: AnswerEvalCase) -> AnswerEvalResult:
        try:
            response = await self._service.answer(
                case.question,
                entity_ids=case.entity_ids,
                min_quality_score=case.min_quality_score,
            )
        # A crash is a failed case, not a failed run: one broken path must not
        # hide the verdict on every other case in the suite.
        except Exception as exc:
            return AnswerEvalResult(
                case_id=case.case_id, passed=False, error=f"{type(exc).__name__}: {exc}"
            )
        return grade_answer(case, response)


class _AnswerService(Protocol):
    """Structural type for the one method the harness calls."""

    async def answer(
        self,
        question: str,
        *,
        entity_ids: Iterable[str] = (),
        min_quality_score: float = 0.0,
    ) -> CopilotResponse:
        """Execute one grounded turn."""
        ...


def _status(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    matched = response.status is case.expect_status
    return DimensionScore(
        dimension=AnswerDimension.STATUS,
        score=_PASS if matched else _FAIL,
        rationale=(
            f"returned {response.status.value} as declared"
            if matched
            else f"expected {case.expect_status.value}, returned {response.status.value}"
        ),
    )


def _grounding(response: CopilotResponse) -> DimensionScore:
    """Every number the reader sees must come from the evidence attached to it."""

    allowed = _evidence_numbers(response)
    written = _numbers(_CITATION.sub(" ", response.answer))
    invented = sorted(value for value in written if value not in allowed)
    if invented:
        shown = ", ".join(str(value) for value in invented[:5])
        return DimensionScore(
            dimension=AnswerDimension.GROUNDING,
            score=_FAIL,
            rationale=(
                f"the answer states {len(invented)} number(s) absent from its evidence: {shown}"
            ),
        )
    return DimensionScore(
        dimension=AnswerDimension.GROUNDING,
        score=_PASS,
        rationale=f"all {len(written)} number(s) trace to the attached evidence",
    )


def _citation(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    cited = {item.dataset_id for item in response.citations}
    missing = sorted(set(case.expect_datasets) - cited)
    if missing:
        return DimensionScore(
            dimension=AnswerDimension.CITATION,
            score=_FAIL,
            rationale=f"expected citations from {', '.join(missing)}",
        )
    known = {item.citation_id for item in response.citations}
    dangling = sorted(set(_CITATION.findall(response.answer)) - known)
    if dangling:
        return DimensionScore(
            dimension=AnswerDimension.CITATION,
            score=_FAIL,
            rationale=f"the answer references unattached citation ids: {', '.join(dangling)}",
        )
    if (
        response.status is CopilotStatus.ANSWERED
        and response.citations
        and not known & set(_CITATION.findall(response.answer))
    ):
        return DimensionScore(
            dimension=AnswerDimension.CITATION,
            score=_FAIL,
            rationale="evidence was attached but the answer points to none of it",
        )
    return DimensionScore(
        dimension=AnswerDimension.CITATION,
        score=_PASS,
        rationale=f"{len(cited)} dataset(s) cited, every reference resolvable",
    )


def _language(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    expected = case.expect_language or question_language(case.question)
    written = _written_language(response.answer)
    if written is None or written is expected:
        return DimensionScore(
            dimension=AnswerDimension.LANGUAGE,
            score=_PASS,
            rationale=f"answered in {expected.value}",
        )
    return DimensionScore(
        dimension=AnswerDimension.LANGUAGE,
        score=_FAIL,
        rationale=f"question is {expected.value}, answer reads as {written.value}",
    )


def _limitations(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    if response.status is not CopilotStatus.ANSWERED or not case.require_limitations:
        return DimensionScore(
            dimension=AnswerDimension.LIMITATIONS,
            score=_PASS,
            rationale="no limitation block is required for this outcome",
        )
    limitations = response.limitations
    if limitations is None or not limitations.freshness:
        return DimensionScore(
            dimension=AnswerDimension.LIMITATIONS,
            score=_FAIL,
            rationale="an answered turn carries no freshness audit",
        )
    return DimensionScore(
        dimension=AnswerDimension.LIMITATIONS,
        score=_PASS,
        rationale=f"{len(limitations.freshness)} source(s) audited for age and coverage",
    )


def _tool_trace(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    ran = {item.tool for item in response.tool_trace}
    missing = sorted(set(case.expect_tools) - ran)
    if missing:
        return DimensionScore(
            dimension=AnswerDimension.TOOL_TRACE,
            score=_FAIL,
            rationale=f"expected tools did not run: {', '.join(missing)}",
        )
    return DimensionScore(
        dimension=AnswerDimension.TOOL_TRACE,
        score=_PASS,
        rationale=f"{len(ran)} tool(s) recorded on the trace",
    )


def _visualization(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    charts = tuple(
        spec for spec in response.visualizations if role_for(spec.type) is not CandidateRole.AUDIT
    )
    if case.expect_no_chart:
        return DimensionScore(
            dimension=AnswerDimension.VISUALIZATION,
            score=_PASS if not charts else _FAIL,
            rationale=(
                "declined to plot, as declared"
                if not charts
                else f"plotted {len(charts)} chart(s) where none was defensible"
            ),
        )
    if case.expect_visualization is None:
        return DimensionScore(
            dimension=AnswerDimension.VISUALIZATION,
            score=_PASS,
            rationale="no visualization was declared for this case",
        )
    types = {spec.type for spec in response.visualizations}
    matched = case.expect_visualization in types
    return DimensionScore(
        dimension=AnswerDimension.VISUALIZATION,
        score=_PASS if matched else _FAIL,
        rationale=(
            f"produced the expected {case.expect_visualization.value}"
            if matched
            else (
                f"expected a {case.expect_visualization.value}, produced "
                f"{', '.join(sorted(item.value for item in types)) or 'nothing'}"
            )
        ),
    )


def _disclosure(case: AnswerEvalCase, response: CopilotResponse) -> DimensionScore:
    """Nothing internal, and nothing forbidden, may reach the reader."""

    surfaces = [response.answer, *(spec.title for spec in response.visualizations)]
    surfaces.extend(spec.headline or "" for spec in response.visualizations)
    haystack = "\n".join(surfaces)
    leaked = sorted({item for item in case.forbidden_substrings if item in haystack})
    if leaked:
        return DimensionScore(
            dimension=AnswerDimension.DISCLOSURE,
            score=_FAIL,
            rationale=f"the answer exposes: {', '.join(leaked)}",
        )
    return DimensionScore(
        dimension=AnswerDimension.DISCLOSURE,
        score=_PASS,
        rationale="no forbidden text reached the reader",
    )


def _evidence_numbers(response: CopilotResponse) -> set[Decimal]:
    """Every figure the response is entitled to state, from its own evidence.

    Derived structurally rather than from the composer's own allowlist, so a
    regression in that allowlist cannot hide here too. Counts the response
    carries about itself — how many rows, how many districts — are included,
    because a truthful summary sentence may state them.
    """

    values: set[Decimal] = set()

    def add(value: object) -> None:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return
        values.add(abs(number))
        # A figure may be written rounded; admit the roundings, never the
        # reverse, so 37.45 written as 37.4 or 37.5 passes while an invented
        # 37.9 fails. Both tie directions are admitted because a writer rounding
        # by hand does not use the banker's rule Decimal defaults to.
        magnitude = abs(number)
        for places in (0, 1, 2):
            exponent = Decimal(1).scaleb(-places)
            for rule in (ROUND_HALF_UP, ROUND_HALF_DOWN):
                values.add(magnitude.quantize(exponent, rounding=rule))

    for citation in response.citations:
        for excerpt_row in citation.excerpt:
            add(excerpt_row.value)
            _add_periods(values, excerpt_row.period)
    series = response.observation_series
    if series is not None:
        for point in series.points:
            add(point.value)
            _add_periods(values, point.period)
        add(len(series.points))
    comparison = response.comparison
    if comparison is not None:
        for change in comparison.changes:
            add(change.first_value)
            add(change.last_value)
            add(change.absolute_change)
            add(change.percent_change)
            _add_periods(values, change.first_period)
            _add_periods(values, change.last_period)
        add(len(comparison.changes))
        add(sum(item.direction == "decreased" for item in comparison.changes))
        add(sum(item.direction == "increased" for item in comparison.changes))
    for candidate in response.candidates:
        add(candidate.score)
        add(candidate.rank)
        for contribution in candidate.contributions:
            add(contribution.raw_value)
            add(contribution.points)
            add(contribution.effective_weight)
    forecast = response.forecast_result
    if forecast is not None:
        for forecast_point in forecast.points:
            add(forecast_point.value)
            add(forecast_point.lower)
            add(forecast_point.upper)
            add(forecast_point.year_gregorian)
            parts = forecast_point.components
            if parts is not None:
                add(parts.base_value)
                add(parts.entering)
                add(parts.ageing_out)
                add(parts.net_change)
                _add_periods(values, parts.base_period)
                # The decomposition is defined by the youth age band, so a
                # sentence naming who reaches 18 or passes 35 is grounded.
                add(YOUTH_MIN_AGE)
                add(YOUTH_MAX_AGE)
        evaluation = forecast.evaluation
        if evaluation is not None:
            for candidate_evaluation in evaluation.candidates:
                for accuracy in candidate_evaluation.accuracy:
                    add(accuracy.horizon_years)
                    add(accuracy.samples)
                    add(accuracy.mape_percent)
                    add(accuracy.p90_ape_percent)
                    add(accuracy.bias_percent)
                    if accuracy.interval_coverage is not None:
                        add(accuracy.interval_coverage * 100)
            # The p90 error is stated as "in 90% of cases".
            add(90)
            add(evaluation.target_coverage * 100)
            add(evaluation.error_quantile * 100)
            for share in (evaluation.rolling_coverage, evaluation.small_area_coverage):
                if share is not None:
                    add(share * 100)
            if evaluation.rolling_samples is not None:
                add(evaluation.rolling_samples)
            # The small-area threshold the coverage sentence names.
            add(SMALL_AREA_POPULATION)
            _add_periods(values, evaluation.base_period)
    impact = response.impact_analysis
    if impact is not None:
        for finding in impact.findings:
            add(finding.baseline_value)
            add(finding.scenario_value)
        add(impact.target_year)
    inspection = response.dataset_inspection
    if inspection is not None:
        add(inspection.entity_count)
        add(inspection.quality_score)
        add(inspection.quality_score * 100)
        _add_periods(values, inspection.period_start)
        _add_periods(values, inspection.period_end)
    analysis = response.multi_dataset_analysis
    if analysis is not None:
        for joined_row in analysis.rows:
            for joined_value in joined_row.values.values():
                add(joined_value)
            _add_periods(values, joined_row.period)
        add(len(analysis.rows))
    for spec in response.visualizations:
        for chart_row in spec.rows:
            for cell in chart_row.values():
                if isinstance(cell, int | float):
                    add(cell)
                elif isinstance(cell, str):
                    _add_periods(values, cell)
    add(len(response.citations))
    add(len(response.visualizations))
    return values


def _add_periods(values: set[Decimal], period: str | None) -> None:
    """Admit the parts of a period, so '2023-01' may be written as a date."""

    if not period:
        return
    for match in _PERIOD.findall(period):
        for part in match.split("-"):
            values.add(Decimal(part))
            values.add(Decimal(part.lstrip("0") or "0"))


def _numbers(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(abs(Decimal(token.replace(",", ""))))
        except InvalidOperation:  # pragma: no cover - the pattern excludes these
            continue
    return found


def _written_language(answer: str) -> NameLanguage | None:
    """Which language the answer reads as, or None when it carries no signal."""

    if _HAN.search(answer):
        return NameLanguage.ZH_HANT
    if _VIETNAMESE.search(answer):
        return NameLanguage.VIETNAMESE
    return None


def visualization_titles(specs: Iterable[VisualizationSpec]) -> tuple[str, ...]:
    """Titles a reviewer sees, exposed for report rendering."""

    return tuple(spec.title for spec in specs)


def load_answer_eval_cases(path: Path) -> tuple[AnswerEvalCase, ...]:
    """Load newline-delimited cases, reporting the line that failed to parse."""

    cases: list[AnswerEvalCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            case = AnswerEvalCase.model_validate_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid answer eval case at {path}:{line_number}") from exc
        if case.case_id in seen:
            raise ValueError(f"duplicate answer eval case {case.case_id!r} at {path}:{line_number}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"answer eval dataset is empty: {path}")
    return tuple(cases)


__all__ = [
    "AnswerDimension",
    "AnswerEvalCase",
    "AnswerEvalHarness",
    "AnswerEvalReport",
    "AnswerEvalResult",
    "DimensionScore",
    "grade_answer",
    "load_answer_eval_cases",
]
