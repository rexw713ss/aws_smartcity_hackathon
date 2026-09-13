"""Compare latency and token use for a small set of Bedrock models."""

import argparse
import json
import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import botocore.exceptions


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _run(client: Any, model_id: str, iterations: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sequence in range(iterations):
        started = time.perf_counter()
        try:
            response = client.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": "Reply with exactly: benchmark-ok"}],
                    }
                ],
                inferenceConfig={"maxTokens": 32, "temperature": 0.0},
            )
        except botocore.exceptions.ClientError as exc:
            error = exc.response.get("Error", {})
            errors.append(
                {
                    "code": str(error.get("Code", "Unknown")),
                    "message": str(error.get("Message", ""))[:300],
                }
            )
            continue
        usage = response.get("usage", {})
        samples.append(
            {
                "sequence": sequence,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "input_tokens": int(usage.get("inputTokens", 0)),
                "output_tokens": int(usage.get("outputTokens", 0)),
            }
        )
    latencies = [sample["latency_ms"] for sample in samples]
    return {
        "model_id": model_id,
        "attempts": iterations,
        "successful": len(samples),
        "p50_ms": _percentile(latencies, 50) if latencies else None,
        "p95_ms": _percentile(latencies, 95) if latencies else None,
        "mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "total_input_tokens": sum(sample["input_tokens"] for sample in samples),
        "total_output_tokens": sum(sample["output_tokens"] for sample in samples),
        "samples": samples,
        "errors": errors,
    }


def _write(prefix: Path, report: dict[str, Any]) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2), "utf-8")
    lines = [
        "# Bedrock model latency benchmark",
        "",
        "| Model | Success | Mean | p50 | p95 | Input tokens | Output tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report["models"]:
        mean = f"{result['mean_ms']:.0f} ms" if result["mean_ms"] is not None else "n/a"
        p50 = f"{result['p50_ms']:.0f} ms" if result["p50_ms"] is not None else "n/a"
        p95 = f"{result['p95_ms']:.0f} ms" if result["p95_ms"] is not None else "n/a"
        lines.append(
            f"| `{result['model_id']}` | {result['successful']}/{result['attempts']} | "
            f"{mean} | {p50} | {p95} | {result['total_input_tokens']} | "
            f"{result['total_output_tokens']} |"
        )
    lines.extend(
        [
            "",
            "Token counts come from Bedrock Converse responses. Dollar cost is intentionally not "
            "estimated without an explicit, versioned model price input.",
        ]
    )
    prefix.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--output-prefix", type=Path, default=Path("artifacts/reports/bedrock-models")
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("bedrock-runtime")
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "region": args.region,
        "models": [_run(client, model, args.iterations) for model in args.model],
    }
    _write(args.output_prefix, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
