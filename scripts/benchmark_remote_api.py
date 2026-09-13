"""Measure the deployed copilot API across a bounded concurrency curve."""

import argparse
import asyncio
import csv
import io
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RemoteSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    concurrency: int
    sequence: int
    latency_ms: float = Field(ge=0)
    http_status: int | None = None
    copilot_status: str | None = None
    ok: bool = False
    error: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    scanned_bytes: int = Field(default=0, ge=0)


class CurvePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    concurrency: int
    requests: int
    successful: int
    error_rate: float
    throughput_requests_per_second: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class RemoteReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    endpoint: str
    curve: tuple[CurvePoint, ...]
    total_input_tokens: int
    total_output_tokens: int
    total_scanned_bytes: int
    usage_complete: bool
    samples: tuple[RemoteSample, ...]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--concurrency", default="1,2,4,8")
    parser.add_argument("--requests-per-level", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=35.0)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("artifacts/reports/aws-api-load"),
    )
    args = parser.parse_args()
    levels = tuple(int(item) for item in args.concurrency.split(",") if item.strip())
    report = asyncio.run(
        benchmark(
            args.base_url.rstrip("/"),
            levels=levels,
            requests_per_level=args.requests_per_level,
            timeout=args.timeout,
        )
    )
    _write(args.output_prefix, report)
    for point in report.curve:
        print(
            f"c={point.concurrency}: {point.successful}/{point.requests} ok, "
            f"p50={point.p50_ms:.0f}ms p95={point.p95_ms:.0f}ms, "
            f"{point.throughput_requests_per_second:.2f} req/s"
        )


async def benchmark(
    base_url: str,
    *,
    levels: Sequence[int],
    requests_per_level: int,
    timeout: float,
) -> RemoteReport:
    if requests_per_level < 1 or not levels or any(level < 1 for level in levels):
        raise ValueError("concurrency levels and requests-per-level must be positive")
    questions = (
        "What is the youth population trend in Banqiao?",
        "Compare the population trend by district from 2023 to 2025",
        "What published youth datasets are available?",
        "Forecast youth population",
    )
    all_samples: list[RemoteSample] = []
    curve: list[CurvePoint] = []
    for level in levels:
        semaphore = asyncio.Semaphore(level)

        async def invoke(
            sequence: int,
            active_level: int = level,
            active_semaphore: asyncio.Semaphore = semaphore,
        ) -> RemoteSample:
            async with active_semaphore:
                return await asyncio.to_thread(
                    _request,
                    base_url,
                    questions[sequence % len(questions)],
                    active_level,
                    sequence,
                    timeout,
                )

        started = time.perf_counter()
        samples = await asyncio.gather(*(invoke(i) for i in range(requests_per_level)))
        wall = time.perf_counter() - started
        all_samples.extend(samples)
        latencies = [item.latency_ms for item in samples]
        successful = sum(item.ok for item in samples)
        curve.append(
            CurvePoint(
                concurrency=level,
                requests=len(samples),
                successful=successful,
                error_rate=(len(samples) - successful) / len(samples),
                throughput_requests_per_second=len(samples) / wall,
                mean_ms=sum(latencies) / len(latencies),
                p50_ms=_percentile(latencies, 50),
                p95_ms=_percentile(latencies, 95),
                p99_ms=_percentile(latencies, 99),
                max_ms=max(latencies),
            )
        )
    model_calls = sum(
        1
        for sample in all_samples
        if sample.ok and sample.copilot_status not in {"unsupported_question", None}
    )
    reported_usage = sum(1 for sample in all_samples if sample.input_tokens or sample.output_tokens)
    return RemoteReport(
        generated_at=datetime.now(UTC),
        endpoint=base_url,
        curve=tuple(curve),
        total_input_tokens=sum(item.input_tokens for item in all_samples),
        total_output_tokens=sum(item.output_tokens for item in all_samples),
        total_scanned_bytes=sum(item.scanned_bytes for item in all_samples),
        usage_complete=model_calls == reported_usage,
        samples=tuple(all_samples),
    )


def _request(
    base_url: str,
    question: str,
    concurrency: int,
    sequence: int,
    timeout: float,
) -> RemoteSample:
    payload = json.dumps({"question": question, "min_quality_score": 0.5}).encode()
    request = urllib.request.Request(
        f"{base_url}/api/v1/copilot/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return RemoteSample(
            concurrency=concurrency,
            sequence=sequence,
            latency_ms=(time.perf_counter() - started) * 1000,
            http_status=exc.code,
            error=f"HTTPError: {exc.reason}"[:300],
        )
    except Exception as exc:
        return RemoteSample(
            concurrency=concurrency,
            sequence=sequence,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}"[:300],
        )
    trace = body.get("tool_trace", []) if isinstance(body, dict) else []
    return RemoteSample(
        concurrency=concurrency,
        sequence=sequence,
        latency_ms=(time.perf_counter() - started) * 1000,
        http_status=status,
        copilot_status=body.get("status") if isinstance(body, dict) else None,
        ok=status == 200 and isinstance(body, dict) and bool(body.get("status")),
        input_tokens=sum(_int(item.get("input_tokens")) for item in trace),
        output_tokens=sum(_int(item.get("output_tokens")) for item in trace),
        scanned_bytes=sum(_int(item.get("scanned_bytes")) for item in trace),
    )


def _int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _write(prefix: Path, report: RemoteReport) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    buffer = io.StringIO()
    fields = list(report.samples[0].model_dump()) if report.samples else []
    writer = csv.DictWriter(buffer, fieldnames=fields)
    if fields:
        writer.writeheader()
        writer.writerows(sample.model_dump() for sample in report.samples)
    prefix.with_suffix(".csv").write_text(buffer.getvalue(), encoding="utf-8")
    lines = [
        "# AWS API load benchmark",
        "",
        f"Endpoint: `{report.endpoint}`",
        "",
        "| Concurrency | Requests | Success | Error rate | p50 | p95 | p99 | Throughput |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for point in report.curve:
        lines.append(
            f"| {point.concurrency} | {point.requests} | {point.successful} | "
            f"{point.error_rate:.1%} | {point.p50_ms:.0f} ms | {point.p95_ms:.0f} ms | "
            f"{point.p99_ms:.0f} ms | {point.throughput_requests_per_second:.2f} req/s |"
        )
    lines.extend(
        [
            "",
            f"Trace usage complete: **{report.usage_complete}**. The deployed API omits "
            "token/scan accounting when this is false, so cost must not be inferred as zero.",
            "",
        ]
    )
    prefix.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
