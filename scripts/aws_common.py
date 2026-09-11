"""Shared core for the verification scripts.

Feature: aws-stage1-foundation, design 3.5.1.

The preflight checker, smoke tester, and data exporter share one result model,
one reporting surface, and one set of safety helpers, so their output is
consistent and their AWS clients are uniformly bounded and read-only by default.
"""

import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from botocore.config import Config
from pydantic import BaseModel, Field

_MAX_DETAIL = 120
_MAX_ERROR_MESSAGE = 200
_REGION_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d$")

# Redaction patterns: access-key ids, and long base64-ish secret/token shapes.
_REDACT_PATTERNS = (
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+])"),
)

# ap-northeast-1 per-unit rate estimates. Confirm against the AWS pricing
# calculator before relying on them; they exist only to size a smoke-test run.
COST_RATES = {
    "s3_request_usd": 0.0000047,
    "glue_request_usd": 0.000001,
    "athena_usd_per_tib": 5.00,
    "stepfunctions_usd_per_transition": 0.000025,
}


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class CheckResult(BaseModel):
    name: str
    outcome: Outcome
    detail: str = Field(default="", max_length=_MAX_DETAIL)
    remediation: str | None = None
    elapsed_ms: int = Field(default=0, ge=0)


class Report(BaseModel):
    tool: str
    region: str
    started_at: datetime
    elapsed_seconds: float = Field(ge=0)
    summary: dict[str, int]
    checks: list[CheckResult]


class RegionError(ValueError):
    """The supplied region is not a syntactically valid AWS region identifier."""


def boto_config() -> Config:
    """Bounded, low-retry client config so a run cannot hang (Req 5.16)."""

    return Config(
        connect_timeout=5,
        read_timeout=5,
        retries={"max_attempts": 2, "mode": "standard"},
    )


def validate_region(value: str) -> str:
    if not _REGION_RE.match(value):
        raise RegionError(f"--region value {value!r} is not a valid AWS region identifier")
    return value


def redact(text: str) -> str:
    """Replace credential-shaped substrings before any value reaches stdout."""

    for pattern in _REDACT_PATTERNS:
        text = pattern.sub("<redacted>", text)
    return text


def run_check(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    """Execute ``fn``; any failure becomes a FAIL row and never propagates."""

    started = datetime.now(UTC)
    try:
        result = fn()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        message = redact(f"{type(exc).__name__}: {exc}")[:_MAX_ERROR_MESSAGE]
        result = CheckResult(name=name, outcome=Outcome.FAIL, detail=message[:_MAX_DETAIL])
    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return result.model_copy(update={"elapsed_ms": elapsed_ms})


def exit_status(results: list[CheckResult]) -> int:
    """1 if any FAIL; WARN and SKIP do not affect the status (Req 5.14)."""

    return 1 if any(r.outcome is Outcome.FAIL for r in results) else 0


def summarize(results: list[CheckResult]) -> dict[str, int]:
    return {outcome.value: sum(1 for r in results if r.outcome is outcome) for outcome in Outcome}


def run_prefix(literal: str) -> str:
    """A run-scoped resource prefix: literal, UTC timestamp, random suffix.

    Lowercase, digits, and hyphens only; capped at 63 characters (Req 6.16).
    """

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(4)
    name = f"{literal}-{stamp}-{suffix}".lower()
    return name[:63]


def render_table(report: Report) -> str:
    lines = [f"{report.tool}   region: {report.region}", ""]
    width = max((len(r.name) for r in report.checks), default=4)
    lines.append(f"{'CHECK':<{width}}  OUTCOME  DETAIL")
    for r in report.checks:
        lines.append(f"{r.name:<{width}}  {r.outcome.value:<7}  {redact(r.detail)}")
    remediations = [
        r for r in report.checks if r.remediation and r.outcome in (Outcome.FAIL, Outcome.WARN)
    ]
    if remediations:
        lines.append("")
        lines.append("remediation:")
        for r in remediations:
            lines.append(f"  {r.name}  {redact(r.remediation or '')}")
    s = report.summary
    lines.append("")
    lines.append(
        f"summary: pass={s.get('pass', 0)} fail={s.get('fail', 0)} "
        f"warn={s.get('warn', 0)} skip={s.get('skip', 0)}   "
        f"elapsed={report.elapsed_seconds:.1f}s"
    )
    return "\n".join(lines)


def render_json(report: Report) -> str:
    return report.model_dump_json(indent=2)
