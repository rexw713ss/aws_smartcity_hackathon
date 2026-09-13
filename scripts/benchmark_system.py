"""Benchmark grounded copilot performance and project its variable request cost."""

import argparse
import asyncio
import csv
import io
from pathlib import Path

from apps.api.dependencies import LocalRuntime
from youth_compass.agent.answer_evals import load_answer_eval_cases
from youth_compass.agent.benchmarking import BenchmarkPricing, BenchmarkReport, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/agent-answers.jsonl"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("artifacts/reports/system-benchmark"),
        help="Writes PREFIX.json, PREFIX.csv, and PREFIX.md.",
    )
    parser.add_argument("--athena-usd-per-tb", type=float, default=5.0)
    parser.add_argument("--athena-min-mb", type=int, default=10)
    parser.add_argument("--model-input-usd-per-million", type=float, default=None)
    parser.add_argument("--model-output-usd-per-million", type=float, default=None)
    args = parser.parse_args()

    pricing = BenchmarkPricing(
        athena_usd_per_tb=args.athena_usd_per_tb,
        athena_min_mb_per_query=args.athena_min_mb,
        model_input_usd_per_million_tokens=args.model_input_usd_per_million,
        model_output_usd_per_million_tokens=args.model_output_usd_per_million,
    )
    report = asyncio.run(
        run_benchmark(
            LocalRuntime(args.data_root).copilot(),
            load_answer_eval_cases(args.cases),
            iterations=args.iterations,
            warmup=args.warmup,
            concurrency=args.concurrency,
            pricing=pricing,
            environment="local-duckdb/deterministic",
        )
    )
    _write_outputs(args.output_prefix, report)
    print(_console_summary(report))


def _write_outputs(prefix: Path, report: BenchmarkReport) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    prefix.with_suffix(".csv").write_text(_samples_csv(report), encoding="utf-8")
    prefix.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")


def _samples_csv(report: BenchmarkReport) -> str:
    buffer = io.StringIO()
    fields = list(report.samples[0].model_dump()) if report.samples else []
    writer = csv.DictWriter(buffer, fieldnames=fields)
    if fields:
        writer.writeheader()
        writer.writerows(sample.model_dump() for sample in report.samples)
    return buffer.getvalue()


def _markdown(report: BenchmarkReport) -> str:
    latency = report.latency
    total_cost = _money(report.projected_total_variable_cost_usd)
    per_request = _money(report.projected_cost_per_request_usd)
    query_calls = sum(item.query_count for item in report.samples)
    billable_queries = sum(item.billable_query_count for item in report.samples)
    lines = [
        "# System performance and cost benchmark",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Environment | {report.environment} |",
        f"| Measured requests | {report.measured_requests} |",
        f"| Passed | {report.passed_requests} ({report.pass_rate:.1%}) |",
        (
            f"| Errors | {report.measured_requests - report.successful_requests} "
            f"({report.error_rate:.1%}) |"
        ),
        f"| Throughput | {report.throughput_requests_per_second:.2f} req/s |",
    ]
    if latency is not None:
        lines.extend(
            [
                f"| Latency mean | {latency.mean_ms:.2f} ms |",
                f"| Latency p50 | {latency.p50_ms:.2f} ms |",
                f"| Latency p95 | {latency.p95_ms:.2f} ms |",
                f"| Latency p99 | {latency.p99_ms:.2f} ms |",
            ]
        )
    lines.extend(
        [
            f"| Raw bytes scanned | {report.total_scanned_bytes:,} |",
            f"| Query calls / billable scans | {query_calls:,} / {billable_queries:,} |",
            f"| Projected Athena billable bytes | {report.total_projected_billable_bytes:,} |",
            (
                f"| Input / output tokens | {report.total_input_tokens:,} / "
                f"{report.total_output_tokens:,} |"
            ),
            f"| Projected variable cost | {total_cost} |",
            f"| Projected cost / request | {per_request} |",
            "",
            "## Latency by case",
            "",
            "| Case | Mean (ms) | p50 (ms) | p95 (ms) | Max (ms) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for case_id, case_latency in report.per_case_latency.items():
        lines.append(
            f"| {case_id} | {case_latency.mean_ms:.2f} | {case_latency.p50_ms:.2f} | "
            f"{case_latency.p95_ms:.2f} | {case_latency.max_ms:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Tool timing",
            "",
            "| Tool | Calls | Mean (ms) | p95 (ms) | Max (ms) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for tool_performance in sorted(report.tools, key=lambda value: value.mean_ms, reverse=True):
        lines.append(
            f"| {tool_performance.tool} | {tool_performance.calls} | "
            f"{tool_performance.mean_ms:.2f} | {tool_performance.p95_ms:.2f} | "
            f"{tool_performance.max_ms:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Cost interpretation",
            "",
            "The run used local DuckDB and deterministic composition, so it incurred no AWS "
            "request charge. The projected Athena amount applies the configured rate and the "
            f"{report.pricing.athena_min_mb_per_query} MB minimum independently to each "
            "non-zero scan. A zero-byte cache hit is not billed. It excludes Lambda, S3, "
            "Glue, DynamoDB, data transfer, and "
            "fixed/provisioned capacity. Model cost is included only when model rates are "
            "provided and every model invocation reports token usage.",
            "",
        ]
    )
    return "\n".join(lines)


def _console_summary(report: BenchmarkReport) -> str:
    latency = report.latency
    latency_text = (
        f"p50={latency.p50_ms:.2f}ms p95={latency.p95_ms:.2f}ms p99={latency.p99_ms:.2f}ms"
        if latency is not None
        else "no latency samples"
    )
    return (
        f"{report.passed_requests}/{report.measured_requests} passed; {latency_text}; "
        f"throughput={report.throughput_requests_per_second:.2f} req/s; "
        f"projected_variable_cost={_money(report.projected_total_variable_cost_usd)}"
    )


def _money(value: float | None) -> str:
    return "unavailable" if value is None else f"${value:.8f}"


if __name__ == "__main__":
    main()
