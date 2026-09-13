"""Collect recent Lambda and Athena metrics after an AWS benchmark run."""

import argparse
import json
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3

_REPORT_RE = re.compile(
    r"Duration: (?P<duration>[0-9.]+) ms.*?Max Memory Used: (?P<memory>\d+) MB"
    r"(?:.*?Init Duration: (?P<init>[0-9.]+) ms)?"
)
_MB = 1_000_000
_TB = 1_000_000_000_000


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values) if values else None,
    }


def _lambda_metrics(client: Any, log_group: str, start_ms: int) -> dict[str, Any]:
    paginator = client.get_paginator("filter_log_events")
    durations: list[float] = []
    cold_starts: list[float] = []
    memory: list[float] = []
    for page in paginator.paginate(
        logGroupName=log_group,
        startTime=start_ms,
        filterPattern='"REPORT RequestId"',
    ):
        for event in page.get("events", []):
            match = _REPORT_RE.search(str(event.get("message", "")))
            if not match:
                continue
            durations.append(float(match.group("duration")))
            memory.append(float(match.group("memory")))
            if match.group("init"):
                cold_starts.append(float(match.group("init")))
    return {
        "invocations_observed": len(durations),
        "duration_ms": _summary(durations),
        "cold_start_init_ms": _summary(cold_starts),
        "max_memory_mb": _summary(memory),
    }


def _athena_metrics(client: Any, workgroup: str, cutoff: datetime) -> dict[str, Any]:
    ids: list[str] = []
    token: str | None = None
    while len(ids) < 100:
        kwargs: dict[str, Any] = {"WorkGroup": workgroup, "MaxResults": 50}
        if token:
            kwargs["NextToken"] = token
        page = client.list_query_executions(**kwargs)
        ids.extend(page.get("QueryExecutionIds", []))
        token = page.get("NextToken")
        if not token:
            break

    executions: list[dict[str, Any]] = []
    for offset in range(0, len(ids), 50):
        response = client.batch_get_query_execution(QueryExecutionIds=ids[offset : offset + 50])
        executions.extend(response.get("QueryExecutions", []))
    recent = [
        item
        for item in executions
        if item.get("Status", {}).get("SubmissionDateTime", cutoff) >= cutoff
    ]
    successful = [item for item in recent if item.get("Status", {}).get("State") == "SUCCEEDED"]
    scanned = [int(item.get("Statistics", {}).get("DataScannedInBytes", 0)) for item in successful]
    engine_ms = [
        float(item.get("Statistics", {}).get("EngineExecutionTimeInMillis", 0))
        for item in successful
    ]
    billable = sum(max(10 * _MB, math.ceil(value / _MB) * _MB) for value in scanned)
    states: dict[str, int] = {}
    for item in recent:
        state = str(item.get("Status", {}).get("State", "UNKNOWN"))
        states[state] = states.get(state, 0) + 1
    return {
        "queries_observed": len(recent),
        "states": states,
        "engine_execution_ms": _summary(engine_ms),
        "data_scanned_bytes": sum(scanned),
        "estimated_billable_bytes": billable,
        "estimated_cost_usd_at_5_per_tb": billable / _TB * 5,
    }


def _write(prefix: Path, report: dict[str, Any]) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2, default=str), "utf-8")
    lam = report["lambda"]
    athena = report["athena"]
    cold = lam["cold_start_init_ms"]
    lines = [
        "# AWS observability benchmark",
        "",
        f"Window: {report['lookback_minutes']} minutes ending {report['generated_at']}",
        "",
        "## Lambda",
        "",
        f"- Invocations observed: {lam['invocations_observed']}",
        f"- Duration p50 / p95: {lam['duration_ms']['p50']:.2f} / "
        f"{lam['duration_ms']['p95']:.2f} ms",
        f"- Cold starts: {cold['count']}; init p50 / p95: {cold['p50']:.2f} / {cold['p95']:.2f} ms"
        if cold["count"]
        else "- Cold starts: 0",
        f"- Maximum memory observed: {lam['max_memory_mb']['max']:.0f} MB",
        "",
        "## Athena",
        "",
        f"- Queries observed: {athena['queries_observed']} ({athena['states']})",
        f"- Engine execution p50 / p95: {athena['engine_execution_ms']['p50'] or 0:.2f} / "
        f"{athena['engine_execution_ms']['p95'] or 0:.2f} ms",
        f"- Raw bytes scanned: {athena['data_scanned_bytes']:,}",
        f"- Estimated billable bytes: {athena['estimated_billable_bytes']:,}",
        f"- Estimated Athena cost: ${athena['estimated_cost_usd_at_5_per_tb']:.6f}",
        "",
        "The Athena estimate applies the 10 MB minimum per successful query and $5/TB rate.",
    ]
    prefix.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--log-group", required=True)
    parser.add_argument("--workgroup", required=True)
    parser.add_argument("--lookback-minutes", type=int, default=30)
    parser.add_argument(
        "--output-prefix", type=Path, default=Path("artifacts/reports/aws-observability")
    )
    args = parser.parse_args()
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=args.lookback_minutes)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    report = {
        "generated_at": now.isoformat(),
        "lookback_minutes": args.lookback_minutes,
        "lambda": _lambda_metrics(
            session.client("logs"), args.log_group, int(cutoff.timestamp() * 1000)
        ),
        "athena": _athena_metrics(session.client("athena"), args.workgroup, cutoff),
    }
    _write(args.output_prefix, report)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
