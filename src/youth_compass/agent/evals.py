"""Reusable offline and Bedrock evaluation harness for decomposition and routing."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import AnalysisOperation, DecomposedQuery, RoutedToolPlan
from youth_compass.agent.planning import QueryDecomposer, SmartToolRouter


class AgentEvalCase(BaseModel):
    """Expected semantic plan for one representative user question."""

    model_config = ConfigDict(frozen=True)

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    question: str = Field(min_length=3)
    entity_ids: tuple[str, ...] = ()
    expected_operations: tuple[AnalysisOperation, ...]
    expected_tools: tuple[str, ...]
    expected_missing_operations: tuple[AnalysisOperation, ...] = ()
    expected_metric_terms: tuple[str, ...] = ()
    expected_time_expression: str | None = None
    expected_clarification: bool = False


class AgentEvalResult(BaseModel):
    """One case result with inspectable model/router artifacts."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool
    failures: tuple[str, ...] = ()
    decomposition: DecomposedQuery
    routed_plan: RoutedToolPlan


class AgentEvalReport(BaseModel):
    """Aggregate report suitable for CI output or Bedrock model comparison."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    results: tuple[AgentEvalResult, ...]


class AgentEvalHarness:
    """Score typed decomposition and routing without executing data tools."""

    def __init__(self, decomposer: QueryDecomposer, router: SmartToolRouter) -> None:
        self._decomposer = decomposer
        self._router = router

    async def run(self, cases: tuple[AgentEvalCase, ...]) -> AgentEvalReport:
        results: list[AgentEvalResult] = []
        for case in cases:
            decomposition = await self._decomposer.decompose(case.question, case.entity_ids)
            routed_plan = self._router.route(decomposition)
            failures = _failures(case, decomposition, routed_plan)
            results.append(
                AgentEvalResult(
                    case_id=case.case_id,
                    passed=not failures,
                    failures=failures,
                    decomposition=decomposition,
                    routed_plan=routed_plan,
                )
            )
        passed = sum(result.passed for result in results)
        total = len(results)
        return AgentEvalReport(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=round(passed / total, 4) if total else 1.0,
            results=tuple(results),
        )


def load_eval_cases(path: Path) -> tuple[AgentEvalCase, ...]:
    """Load newline-delimited cases with line-numbered validation errors."""

    cases: list[AgentEvalCase] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            case = AgentEvalCase.model_validate_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid eval case at {path}:{line_number}") from exc
        if case.case_id in seen:
            raise ValueError(f"duplicate eval case {case.case_id!r} at {path}:{line_number}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"eval dataset is empty: {path}")
    return tuple(cases)


def _failures(
    case: AgentEvalCase,
    decomposition: DecomposedQuery,
    routed_plan: RoutedToolPlan,
) -> tuple[str, ...]:
    failures: list[str] = []
    checks: tuple[tuple[str, object, object], ...] = (
        ("operations", decomposition.operations, case.expected_operations),
        (
            "tools",
            tuple(step.tool_name for step in routed_plan.steps),
            case.expected_tools,
        ),
        (
            "missing_operations",
            routed_plan.missing_operations,
            case.expected_missing_operations,
        ),
        ("metric_terms", decomposition.metric_terms, case.expected_metric_terms),
        ("time_expression", decomposition.time_expression, case.expected_time_expression),
        (
            "needs_clarification",
            decomposition.needs_clarification,
            case.expected_clarification,
        ),
    )
    for label, actual, expected in checks:
        if actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")
    return tuple(failures)
