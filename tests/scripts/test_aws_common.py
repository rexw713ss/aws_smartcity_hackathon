"""Shared verification-script core.

Feature: aws-stage1-foundation
Properties 26 (report consistency and redaction), 27 (json matches table),
28 first clause (exit status), 29 (check isolation), 31 (region validation and
bounded config), 38 (run prefix).
"""

import json
import random
import re
from datetime import UTC, datetime

import pytest

from scripts.aws_common import (
    CheckResult,
    Outcome,
    RegionError,
    Report,
    boto_config,
    exit_status,
    redact,
    render_json,
    render_table,
    run_check,
    run_prefix,
    summarize,
    validate_region,
)


def _report(checks: list[CheckResult]) -> Report:
    return Report(
        tool="test",
        region="ap-northeast-1",
        started_at=datetime.now(UTC),
        elapsed_seconds=1.0,
        summary=summarize(checks),
        checks=checks,
    )


# --- Property 26 -------------------------------------------------------------


def test_property_26_summary_counts_sum_and_match() -> None:
    rng = random.Random(26)
    outcomes = list(Outcome)
    for _ in range(100):
        checks = [
            CheckResult(name=f"c{i}", outcome=rng.choice(outcomes))
            for i in range(rng.randint(1, 8))
        ]
        summary = summarize(checks)
        assert sum(summary.values()) == len(checks)
        for outcome in Outcome:
            assert summary[outcome.value] == sum(1 for c in checks if c.outcome is outcome)


def test_property_26_detail_is_capped_at_120() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic max_length
        CheckResult(name="x", outcome=Outcome.PASS, detail="y" * 121)


def test_property_26_remediation_lines_equal_fail_plus_warn() -> None:
    checks = [
        CheckResult(name="a", outcome=Outcome.PASS),
        CheckResult(name="b", outcome=Outcome.FAIL, remediation="do X"),
        CheckResult(name="c", outcome=Outcome.WARN, remediation="do Y"),
        CheckResult(name="d", outcome=Outcome.SKIP, remediation="ignored"),
    ]
    table = render_table(_report(checks))
    assert table.count("do X") == 1
    assert table.count("do Y") == 1
    # SKIP remediation is not rendered
    assert "ignored" not in table


def test_property_26_output_is_redacted() -> None:
    checks = [
        CheckResult(name="creds", outcome=Outcome.PASS, detail="key AKIAIOSFODNN7EXAMPLE seen")
    ]
    table = render_table(_report(checks))
    assert "AKIAIOSFODNN7EXAMPLE" not in table
    assert "<redacted>" in table


def test_redact_masks_secret_shapes() -> None:
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # 40 chars
    assert secret not in redact(f"secret={secret}")


# --- Property 27 -------------------------------------------------------------


def test_property_27_json_matches_table_fields() -> None:
    checks = [
        CheckResult(name="a", outcome=Outcome.PASS, detail="ok"),
        CheckResult(name="b", outcome=Outcome.FAIL, detail="bad", remediation="fix"),
    ]
    report = _report(checks)
    parsed = json.loads(render_json(report))
    assert [c["name"] for c in parsed["checks"]] == ["a", "b"]
    assert [c["outcome"] for c in parsed["checks"]] == ["pass", "fail"]
    assert parsed["checks"][1]["remediation"] == "fix"


# --- Property 28 (first clause) ----------------------------------------------


def test_property_28_exit_status_is_pure_function_of_outcomes() -> None:
    rng = random.Random(28)
    outcomes = list(Outcome)
    for _ in range(100):
        checks = [
            CheckResult(name=f"c{i}", outcome=rng.choice(outcomes))
            for i in range(rng.randint(1, 8))
        ]
        expected = 1 if any(c.outcome is Outcome.FAIL for c in checks) else 0
        assert exit_status(checks) == expected


# --- Property 29 -------------------------------------------------------------


def test_property_29_check_exception_isolates_to_a_fail_row() -> None:
    def boom() -> CheckResult:
        raise RuntimeError("kaboom " + "x" * 500)

    result = run_check("explodes", boom)
    assert result.outcome is Outcome.FAIL
    assert "RuntimeError" in result.detail
    assert len(result.detail) <= 120


def test_property_29_keyboard_interrupt_propagates() -> None:
    def interrupt() -> CheckResult:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_check("x", interrupt)


# --- Property 31 -------------------------------------------------------------


def test_property_31_invalid_region_rejected() -> None:
    for bad in ("", "US-EAST-1", "useast1", "ap_northeast_1", "ap-northeast"):
        with pytest.raises(RegionError):
            validate_region(bad)


def test_property_31_valid_regions_accepted() -> None:
    for good in ("ap-northeast-1", "us-east-1", "eu-west-3", "ap-southeast-2"):
        assert validate_region(good) == good


def test_property_31_boto_config_is_bounded() -> None:
    cfg = boto_config()
    assert cfg.connect_timeout == 5
    assert cfg.read_timeout == 5
    assert cfg.retries["max_attempts"] == 2


# --- Property 38 -------------------------------------------------------------


def test_property_38_run_prefix_charset_length_and_uniqueness() -> None:
    seen = set()
    for _ in range(100):
        name = run_prefix("ycsmoke")
        assert re.fullmatch(r"[a-z0-9-]+", name)
        assert len(name) <= 63
        assert name.startswith("ycsmoke-")
        seen.add(name)
    assert len(seen) == 100
