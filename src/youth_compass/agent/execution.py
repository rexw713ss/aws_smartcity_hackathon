"""Execution of a routed tool plan, in the order the plan declares.

``RoutedToolPlan`` carried ``depends_on`` — a genuine DAG — and nothing ran it.
The plan described what would happen while hand-written ``if`` chains decided
what actually happened, so the two could disagree and no test would notice. This
module makes the plan the thing that executes.

An executor holds one handler per ``AnalysisOperation``. It walks the steps in
dependency order, gives each handler a shared ``ExecutionState`` to read what
earlier steps produced and to record what this step produced, and traces every
step with the time it took. A handler that raises a domain error stops the walk:
the plan failed at a named step, which is a far more useful thing to report than
a partial answer assembled from whatever succeeded.

What this deliberately does not do is decide *what* a step means. The handlers
own that, and they are the same bounded tools as before. The change is that their
order, their dependencies, and their accounting now come from one place.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from youth_compass.agent.contracts import (
    AnalysisOperation,
    DecomposedQuery,
    RoutedToolPlan,
    RoutedToolStep,
    ToolTrace,
)
from youth_compass.domain.errors import YouthCompassError

#: How much of a failure message a step trace keeps.
_TRACE_SUMMARY_LIMIT = 300


@dataclass
class ExecutionState:
    """What the steps executed so far have produced.

    Deliberately a plain mutable bag rather than a typed record per pipeline. A
    step handler reads the keys its declared dependencies promised and writes the
    key it owns; the router already guarantees a step only runs after the
    operations it ``requires`` have completed, so a missing key is a routing bug
    rather than a case to handle. ``require`` turns that into a loud failure
    instead of a ``None`` propagating into an answer.
    """

    decomposition: DecomposedQuery
    min_quality_score: float = 0.0
    values: dict[str, Any] = field(default_factory=dict)
    #: Accounting the current step wants on its trace entry. The executor drains
    #: this after each step, so a handler reports what it spent without having to
    #: build the trace entry itself.
    pending_cost: dict[str, int] = field(default_factory=dict)

    def put(self, key: str, value: Any) -> None:
        self.values[key] = value

    def charge(
        self,
        *,
        scanned_bytes: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Attribute a cost to the step currently running."""

        for key, value in (
            ("scanned_bytes", scanned_bytes),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if value is not None:
                self.pending_cost[key] = value

    def drain_cost(self) -> dict[str, int]:
        """Take the accounting recorded for the step that just finished."""

        drained = dict(self.pending_cost)
        self.pending_cost.clear()
        return drained

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        """Read a value an earlier step must have produced."""

        if key not in self.values:
            raise PlanExecutionError(
                f"step ordering is wrong: {key!r} was needed before it was produced"
            )
        return self.values[key]


class PlanExecutionError(YouthCompassError):
    """The plan itself could not be executed, independently of the data."""


#: A handler runs one step and records its result on the state. It returns the
#: trace summary for the step; the executor owns outcome and timing.
type StepHandler = Callable[[ExecutionState, RoutedToolStep], Awaitable[str]]


def execution_order(plan: RoutedToolPlan) -> tuple[RoutedToolStep, ...]:
    """Return the steps in an order that satisfies every ``depends_on``.

    The router emits steps in a valid order already, so this is usually the
    identity. It exists because ``depends_on`` is either meaningful or it is
    decoration: sorting by it here is what makes the field load-bearing, and it
    is what catches a plan that names a dependency it never produced or a cycle
    that would otherwise deadlock a future concurrent executor.
    """

    by_id = {step.step_id: step for step in plan.steps}
    duplicates = len(by_id) != len(plan.steps)
    if duplicates:
        raise PlanExecutionError("a routed plan must not repeat a step id")
    unknown = sorted(
        {
            dependency
            for step in plan.steps
            for dependency in step.depends_on
            if dependency not in by_id
        }
    )
    if unknown:
        raise PlanExecutionError(f"plan depends on steps that do not exist: {', '.join(unknown)}")

    # A stable topological sort: among the steps whose dependencies are settled,
    # always take the one the router emitted first.
    #
    # Taking every ready step at once would be wrong, because `depends_on`
    # under-specifies the order. It is derived from a capability's `requires`,
    # and some operations legitimately declare none while still needing to run
    # last — `explain_lineage` requires nothing, yet it cites a series that
    # `query_observations` has to have produced. The router's sequence encodes
    # that intent, so this respects it and uses `depends_on` to catch a plan whose
    # declared edges contradict it.
    ordered: list[RoutedToolStep] = []
    settled: set[str] = set()
    remaining = list(plan.steps)
    while remaining:
        ready = next(
            (step for step in remaining if set(step.depends_on) <= settled),
            None,
        )
        if ready is None:
            stuck = ", ".join(step.step_id for step in remaining)
            raise PlanExecutionError(f"plan has a dependency cycle among: {stuck}")
        ordered.append(ready)
        settled.add(ready.step_id)
        remaining.remove(ready)
    return tuple(ordered)


class PlanExecutor:
    """Run a routed plan's steps in dependency order, tracing each one."""

    def __init__(self, handlers: dict[AnalysisOperation, StepHandler]) -> None:
        self._handlers = dict(handlers)

    def handles(self, operation: AnalysisOperation) -> bool:
        """True when this executor has a handler for ``operation``."""

        return operation in self._handlers

    def supports(self, plan: RoutedToolPlan) -> bool:
        """True when every step in the plan has a registered handler."""

        return all(step.operation in self._handlers for step in plan.steps)

    def unhandled(self, plan: RoutedToolPlan) -> tuple[AnalysisOperation, ...]:
        """Operations this executor was routed but cannot run."""

        return tuple(
            dict.fromkeys(
                step.operation for step in plan.steps if step.operation not in self._handlers
            )
        )

    async def run(
        self,
        plan: RoutedToolPlan,
        state: ExecutionState,
        trace: list[ToolTrace],
    ) -> ExecutionState:
        """Execute every step, or stop at the first one that fails.

        A domain error is re-raised after being traced. The caller decides what a
        failed step means for the answer — usually a refusal naming the gap — but
        it always learns which step failed and why.
        """

        for step in execution_order(plan):
            handler = self._handlers.get(step.operation)
            if handler is None:
                raise PlanExecutionError(
                    f"no handler registered for operation {step.operation.value!r}"
                )
            started = time.perf_counter()
            try:
                summary = await handler(state, step)
            except YouthCompassError as exc:
                trace.append(
                    ToolTrace(
                        tool=step.tool_name,
                        outcome="unavailable",
                        summary=str(exc)[:_TRACE_SUMMARY_LIMIT],
                        duration_ms=_elapsed_ms(started),
                        step_id=step.step_id,
                        # A failed step still spent what it spent. A query that
                        # scanned a gigabyte and then tripped the row guard is
                        # billed exactly like one that succeeded.
                        **state.drain_cost(),
                    )
                )
                raise
            trace.append(
                ToolTrace(
                    tool=step.tool_name,
                    outcome="ok",
                    summary=summary[:_TRACE_SUMMARY_LIMIT],
                    duration_ms=_elapsed_ms(started),
                    step_id=step.step_id,
                    **state.drain_cost(),
                )
            )
        return state


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


__all__ = [
    "ExecutionState",
    "PlanExecutionError",
    "PlanExecutor",
    "StepHandler",
    "execution_order",
]
