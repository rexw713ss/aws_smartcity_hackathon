"""Repeatable performance and variable-cost measurement for copilot turns.

The benchmark measures the same service object used by the API. It deliberately
keeps observed local work and projected AWS charges separate: a DuckDB byte
count is useful for comparing requests, but it is not an AWS bill. The Athena
projection applies the public per-query rounding/minimum so the estimate is not
misleadingly close to zero for small Parquet scans.
"""

import asyncio
import math
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.answer_evals import AnswerEvalCase, grade_answer
from youth_compass.agent.contracts import CopilotResponse

_MB = 1_000_000
_TB = 1_000_000_000_000


class BenchmarkPricing(BaseModel):
    """Rates used for projections; model rates are model-specific inputs."""

    model_config = ConfigDict(frozen=True)

    athena_usd_per_tb: float = Field(default=5.0, ge=0)
    athena_min_mb_per_query: int = Field(default=10, ge=0)
    model_input_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    model_output_usd_per_million_tokens: float | None = Field(default=None, ge=0)


class BenchmarkSample(BaseModel):
    """One timed request and the accounting reported by its trace."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    iteration: int = Field(ge=1)
    latency_ms: float = Field(ge=0)
    status: str | None = None
    passed: bool = False
    error: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    scanned_bytes: int = Field(default=0, ge=0)
    query_count: int = Field(default=0, ge=0)
    billable_query_count: int = Field(default=0, ge=0)
    model_invocation_count: int = Field(default=0, ge=0)
    model_usage_complete: bool = True
    projected_billable_bytes: int = Field(default=0, ge=0)
    projected_athena_cost_usd: float = Field(default=0, ge=0)
    projected_model_cost_usd: float | None = Field(default=None, ge=0)


class LatencySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class ToolPerformance(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    calls: int = Field(ge=1)
    mean_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class BenchmarkReport(BaseModel):
    """Machine-readable benchmark result suitable for a CI artifact."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    environment: str
    case_count: int = Field(ge=0)
    iterations: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    warmup_requests: int = Field(ge=0)
    measured_requests: int = Field(ge=0)
    successful_requests: int = Field(ge=0)
    passed_requests: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    pass_rate: float = Field(ge=0, le=1)
    wall_time_seconds: float = Field(ge=0)
    throughput_requests_per_second: float = Field(ge=0)
    latency: LatencySummary | None = None
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_scanned_bytes: int = Field(ge=0)
    total_projected_billable_bytes: int = Field(ge=0)
    projected_athena_cost_usd: float = Field(ge=0)
    projected_model_cost_usd: float | None = Field(default=None, ge=0)
    projected_total_variable_cost_usd: float | None = Field(default=None, ge=0)
    projected_cost_per_request_usd: float | None = Field(default=None, ge=0)
    pricing: BenchmarkPricing
    per_case_latency: dict[str, LatencySummary]
    tools: tuple[ToolPerformance, ...]
    samples: tuple[BenchmarkSample, ...]


class _AnswerService(Protocol):
    async def answer(
        self,
        question: str,
        *,
        entity_ids: Iterable[str] = (),
        min_quality_score: float = 0.0,
    ) -> CopilotResponse: ...


async def run_benchmark(
    service: _AnswerService,
    cases: Sequence[AnswerEvalCase],
    *,
    iterations: int = 5,
    warmup: int = 1,
    concurrency: int = 1,
    pricing: BenchmarkPricing | None = None,
    environment: str = "local",
) -> BenchmarkReport:
    """Warm the runtime, measure all case/iteration pairs, and aggregate them."""

    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if warmup < 0:
        raise ValueError("warmup must not be negative")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    rates = pricing or BenchmarkPricing()

    for _ in range(warmup):
        for case in cases:
            await _invoke(service, case, 1, rates)

    semaphore = asyncio.Semaphore(concurrency)
    trace_durations: dict[str, list[float]] = defaultdict(list)

    async def measured(case: AnswerEvalCase, iteration: int) -> BenchmarkSample:
        async with semaphore:
            sample, durations = await _invoke(service, case, iteration, rates)
            for tool, values in durations.items():
                trace_durations[tool].extend(values)
            return sample

    started = time.perf_counter()
    samples = await asyncio.gather(
        *(measured(case, iteration) for iteration in range(1, iterations + 1) for case in cases)
    )
    wall_time = time.perf_counter() - started
    return _aggregate(
        tuple(samples),
        case_count=len(cases),
        iterations=iterations,
        concurrency=concurrency,
        warmup_requests=warmup * len(cases),
        wall_time=wall_time,
        trace_durations=trace_durations,
        pricing=rates,
        environment=environment,
    )


async def _invoke(
    service: _AnswerService,
    case: AnswerEvalCase,
    iteration: int,
    pricing: BenchmarkPricing,
) -> tuple[BenchmarkSample, dict[str, list[float]]]:
    started = time.perf_counter()
    try:
        response = await service.answer(
            case.question,
            entity_ids=case.entity_ids,
            min_quality_score=case.min_quality_score,
        )
    except Exception as exc:
        return (
            BenchmarkSample(
                case_id=case.case_id,
                iteration=iteration,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}"[:500],
            ),
            {},
        )

    input_tokens = sum(item.input_tokens or 0 for item in response.tool_trace)
    output_tokens = sum(item.output_tokens or 0 for item in response.tool_trace)
    model_traces = [
        item
        for item in response.tool_trace
        if (item.tool == "answer_composer" and item.outcome == "model")
        or (item.tool == "query_decomposer" and "planned by model" in item.summary)
    ]
    model_usage_complete = all(
        item.input_tokens is not None and item.output_tokens is not None for item in model_traces
    )
    query_scans = [
        item.scanned_bytes for item in response.tool_trace if item.scanned_bytes is not None
    ]
    scanned_bytes = sum(query_scans)
    billable_scans = [value for value in query_scans if value > 0]
    billable_bytes = sum(_athena_billable_bytes(value, pricing) for value in billable_scans)
    athena_cost = billable_bytes / _TB * pricing.athena_usd_per_tb
    model_cost = _model_cost(
        input_tokens,
        output_tokens,
        len(model_traces),
        model_usage_complete,
        pricing,
    )
    durations: dict[str, list[float]] = defaultdict(list)
    for item in response.tool_trace:
        if item.duration_ms is not None:
            durations[item.tool].append(float(item.duration_ms))
    return (
        BenchmarkSample(
            case_id=case.case_id,
            iteration=iteration,
            latency_ms=(time.perf_counter() - started) * 1000,
            status=response.status.value,
            passed=grade_answer(case, response).passed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            scanned_bytes=scanned_bytes,
            query_count=len(query_scans),
            billable_query_count=len(billable_scans),
            model_invocation_count=len(model_traces),
            model_usage_complete=model_usage_complete,
            projected_billable_bytes=billable_bytes,
            projected_athena_cost_usd=athena_cost,
            projected_model_cost_usd=model_cost,
        ),
        durations,
    )


def _athena_billable_bytes(scanned_bytes: int, pricing: BenchmarkPricing) -> int:
    rounded_mb = math.ceil(scanned_bytes / _MB) if scanned_bytes else 0
    return max(pricing.athena_min_mb_per_query, rounded_mb) * _MB


def _model_cost(
    input_tokens: int,
    output_tokens: int,
    invocation_count: int,
    usage_complete: bool,
    pricing: BenchmarkPricing,
) -> float | None:
    if invocation_count == 0:
        return 0.0
    if not usage_complete:
        return None
    if (
        pricing.model_input_usd_per_million_tokens is None
        or pricing.model_output_usd_per_million_tokens is None
    ):
        return None
    return (
        input_tokens * pricing.model_input_usd_per_million_tokens
        + output_tokens * pricing.model_output_usd_per_million_tokens
    ) / 1_000_000


def _aggregate(
    samples: tuple[BenchmarkSample, ...],
    *,
    case_count: int,
    iterations: int,
    concurrency: int,
    warmup_requests: int,
    wall_time: float,
    trace_durations: dict[str, list[float]],
    pricing: BenchmarkPricing,
    environment: str,
) -> BenchmarkReport:
    successful = [item for item in samples if item.error is None]
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in samples:
        grouped[item.case_id].append(item.latency_ms)
    model_costs = [item.projected_model_cost_usd for item in samples]
    model_cost = (
        None
        if any(item is None for item in model_costs)
        else sum(item or 0 for item in model_costs)
    )
    athena_cost = sum(item.projected_athena_cost_usd for item in samples)
    total_cost = athena_cost + model_cost if model_cost is not None else None
    request_count = len(samples)
    return BenchmarkReport(
        generated_at=datetime.now(UTC),
        environment=environment,
        case_count=case_count,
        iterations=iterations,
        concurrency=concurrency,
        warmup_requests=warmup_requests,
        measured_requests=request_count,
        successful_requests=len(successful),
        passed_requests=sum(item.passed for item in samples),
        error_rate=(request_count - len(successful)) / request_count if request_count else 0,
        pass_rate=sum(item.passed for item in samples) / request_count if request_count else 1,
        wall_time_seconds=wall_time,
        throughput_requests_per_second=request_count / wall_time if wall_time else 0,
        latency=_latency([item.latency_ms for item in samples]) if samples else None,
        total_input_tokens=sum(item.input_tokens for item in samples),
        total_output_tokens=sum(item.output_tokens for item in samples),
        total_scanned_bytes=sum(item.scanned_bytes for item in samples),
        total_projected_billable_bytes=sum(item.projected_billable_bytes for item in samples),
        projected_athena_cost_usd=athena_cost,
        projected_model_cost_usd=model_cost,
        projected_total_variable_cost_usd=total_cost,
        projected_cost_per_request_usd=(
            total_cost / request_count if total_cost is not None and request_count else None
        ),
        pricing=pricing,
        per_case_latency={name: _latency(values) for name, values in sorted(grouped.items())},
        tools=tuple(
            ToolPerformance(
                tool=tool,
                calls=len(values),
                mean_ms=sum(values) / len(values),
                p95_ms=_percentile(values, 95),
                max_ms=max(values),
            )
            for tool, values in sorted(trace_durations.items())
        ),
        samples=samples,
    )


def _latency(values: Sequence[float]) -> LatencySummary:
    return LatencySummary(
        min_ms=min(values),
        mean_ms=sum(values) / len(values),
        p50_ms=_percentile(values, 50),
        p95_ms=_percentile(values, 95),
        p99_ms=_percentile(values, 99),
        max_ms=max(values),
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    """Linearly interpolated percentile, matching common monitoring tools."""

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
