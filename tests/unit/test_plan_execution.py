"""The routed plan is executed, not merely described.

`RoutedToolPlan` carried a `depends_on` DAG that nothing ran: the plan said what
would happen while hand-written branches decided what did. These tests hold the
executor to the plan, and hold the plan to the trace it produces.
"""

import asyncio

import pytest

from youth_compass.agent import (
    AnalysisOperation,
    DecomposedQuery,
    RoutedToolPlan,
    RoutedToolStep,
    ToolTrace,
)
from youth_compass.agent.execution import (
    ExecutionState,
    PlanExecutionError,
    PlanExecutor,
    execution_order,
)
from youth_compass.domain.errors import QueryExecutionError


def _step(index: int, operation: AnalysisOperation, *depends_on: str) -> RoutedToolStep:
    return RoutedToolStep(
        step_id=f"step_{index}",
        operation=operation,
        tool_name=operation.value,
        depends_on=depends_on,
    )


def _state() -> ExecutionState:
    return ExecutionState(
        decomposition=DecomposedQuery(
            original_question="anything",
            objective="test",
            operations=(AnalysisOperation.SEARCH_CATALOG,),
        )
    )


def _recorder(order: list[str]):
    async def handler(state: ExecutionState, step: RoutedToolStep) -> str:
        del state
        order.append(step.step_id)
        return f"ran {step.step_id}"

    return handler


def test_a_step_declaring_no_dependency_does_not_jump_the_queue() -> None:
    """`depends_on` under-specifies the order, so the router's sequence stands.

    `explain_lineage` requires no operation and therefore declares no dependency,
    yet it cites a series `query_observations` must already have produced. An
    executor that ran every dependency-free step first put lineage before the
    query and asked for a series nothing had produced. This is that regression.
    """

    plan = RoutedToolPlan(
        steps=(
            _step(1, AnalysisOperation.SEARCH_CATALOG),
            _step(2, AnalysisOperation.INSPECT_DATASET, "step_1"),
            _step(3, AnalysisOperation.QUERY_OBSERVATIONS, "step_2"),
            _step(4, AnalysisOperation.EXPLAIN_LINEAGE),
        )
    )

    assert [step.step_id for step in execution_order(plan)] == [
        "step_1",
        "step_2",
        "step_3",
        "step_4",
    ]


def test_a_step_whose_dependency_comes_later_is_reordered_behind_it() -> None:
    plan = RoutedToolPlan(
        steps=(
            _step(1, AnalysisOperation.QUERY_OBSERVATIONS, "step_2"),
            _step(2, AnalysisOperation.INSPECT_DATASET),
        )
    )

    assert [step.step_id for step in execution_order(plan)] == ["step_2", "step_1"]


def test_a_dependency_cycle_is_refused_rather_than_looping() -> None:
    plan = RoutedToolPlan(
        steps=(
            _step(1, AnalysisOperation.QUERY_OBSERVATIONS, "step_2"),
            _step(2, AnalysisOperation.INSPECT_DATASET, "step_1"),
        )
    )

    with pytest.raises(PlanExecutionError, match="dependency cycle"):
        execution_order(plan)


def test_a_dependency_on_a_step_that_does_not_exist_is_refused() -> None:
    plan = RoutedToolPlan(steps=(_step(1, AnalysisOperation.QUERY_OBSERVATIONS, "step_9"),))

    with pytest.raises(PlanExecutionError, match="do not exist"):
        execution_order(plan)


def test_every_executed_step_is_traced_with_its_id_and_duration() -> None:
    """The trace has to be joinable to the plan, or the two can still drift."""

    order: list[str] = []
    plan = RoutedToolPlan(
        steps=(
            _step(1, AnalysisOperation.SEARCH_CATALOG),
            _step(2, AnalysisOperation.INSPECT_DATASET, "step_1"),
        )
    )
    executor = PlanExecutor(
        {
            AnalysisOperation.SEARCH_CATALOG: _recorder(order),
            AnalysisOperation.INSPECT_DATASET: _recorder(order),
        }
    )
    trace: list[ToolTrace] = []

    asyncio.run(executor.run(plan, _state(), trace))

    assert order == ["step_1", "step_2"]
    assert [item.step_id for item in trace] == ["step_1", "step_2"]
    assert all(item.duration_ms is not None for item in trace)
    assert all(item.outcome == "ok" for item in trace)


def test_a_failing_step_is_traced_and_stops_the_walk() -> None:
    """A partial answer from whatever succeeded is worse than a named failure."""

    order: list[str] = []

    async def failing(state: ExecutionState, step: RoutedToolStep) -> str:
        del state, step
        raise QueryExecutionError("the dataset has no rows for this scope")

    plan = RoutedToolPlan(
        steps=(
            _step(1, AnalysisOperation.SEARCH_CATALOG),
            _step(2, AnalysisOperation.INSPECT_DATASET, "step_1"),
            _step(3, AnalysisOperation.QUERY_OBSERVATIONS, "step_2"),
        )
    )
    executor = PlanExecutor(
        {
            AnalysisOperation.SEARCH_CATALOG: _recorder(order),
            AnalysisOperation.INSPECT_DATASET: failing,
            AnalysisOperation.QUERY_OBSERVATIONS: _recorder(order),
        }
    )
    trace: list[ToolTrace] = []

    with pytest.raises(QueryExecutionError):
        asyncio.run(executor.run(plan, _state(), trace))

    assert order == ["step_1"], "no step after the failure may run"
    assert [item.outcome for item in trace] == ["ok", "unavailable"]
    assert "no rows for this scope" in trace[-1].summary


def test_reading_a_value_an_earlier_step_never_produced_fails_loudly() -> None:
    state = _state()

    with pytest.raises(PlanExecutionError, match="step ordering is wrong"):
        state.require("series")


def test_an_unregistered_operation_is_reported_rather_than_skipped() -> None:
    plan = RoutedToolPlan(steps=(_step(1, AnalysisOperation.SIMULATE_SCENARIO),))
    executor = PlanExecutor({AnalysisOperation.SEARCH_CATALOG: _recorder([])})

    assert executor.supports(plan) is False
    assert executor.unhandled(plan) == (AnalysisOperation.SIMULATE_SCENARIO,)
    with pytest.raises(PlanExecutionError, match="no handler registered"):
        asyncio.run(executor.run(plan, _state(), []))
