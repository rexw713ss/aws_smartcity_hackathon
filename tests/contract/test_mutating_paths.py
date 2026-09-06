"""Mutating-path and deferred-service guards over the finished scripts.

Feature: aws-stage1-foundation, Property 17.

Every AWS-mutating entry point must sit behind an explicit flag or make target,
and no deferred-service inference/training/deployment API may appear under
scripts/.
"""

import ast
from pathlib import Path

import pytest

from scripts import aws_smoke_test, aws_teardown

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# Read-only / no-charge deferred-service calls the preflight is allowed to make.
ALLOWED_DEFERRED_CALLS = {"list_foundation_models"}
# Charge-incurring deferred-service calls that must never appear under scripts/.
FORBIDDEN_DEFERRED_CALLS = {
    "invoke_model",
    "invoke_model_with_response_stream",
    "create_model_customization_job",
    "create_endpoint",
    "create_training_job",
    "create_hyper_parameter_tuning_job",
    "create_notebook_instance",
    "start_model_invocation_job",
}


def test_smoke_test_defaults_to_moto_no_real_calls(capsys: pytest.CaptureFixture[str]) -> None:
    # Property 17: the mutating path (real AWS) is unreachable without --real.
    code = aws_smoke_test.run_smoke("ap-northeast-1", real=False)
    out = capsys.readouterr().out
    assert "mode: moto" in out
    assert code == 0


def test_teardown_refuses_unattended_without_flag() -> None:
    proceeded = aws_teardown.confirm_teardown(
        "123456789012",
        "ap-northeast-1",
        ["StackA"],
        responder=lambda _prompt: "",
        stdin_isatty=False,
        assume_yes=False,
    )
    assert proceeded is False


def test_no_forbidden_deferred_service_calls_under_scripts() -> None:
    findings: list[str] = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_DEFERRED_CALLS:
                findings.append(f"{path.name}:{node.lineno}: {node.attr}")
    assert not findings, "charge-incurring deferred-service calls found:\n" + "\n".join(findings)
