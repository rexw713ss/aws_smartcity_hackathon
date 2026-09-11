"""Smoke tester under Moto.

Feature: aws-stage1-foundation
Properties 34 (Moto mode is free and offline), 35 (data round-trips),
36 (cleanup leaves nothing), 40 (real path refuses without prerequisites).
"""

import time

import boto3
import pytest

from scripts import aws_smoke_test
from scripts.aws_smoke_test import SmokeTester

REGION = "ap-northeast-1"


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def test_property_34_moto_mode_is_free_and_offline(capsys: pytest.CaptureFixture[str]) -> None:
    code = aws_smoke_test.run_smoke(REGION, real=False)
    out = capsys.readouterr().out
    assert code == 0
    assert "mode: moto" in out
    assert "0.00 USD" in out


def test_property_35_and_36_end_to_end_leaves_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = time.monotonic()
    code = aws_smoke_test.run_smoke(REGION, real=False)
    duration = time.monotonic() - started
    out = capsys.readouterr().out
    assert code == 0
    assert "0 survived" in out
    assert duration < 60


def test_steps_pass_and_simulated_rows_labelled(capsys: pytest.CaptureFixture[str]) -> None:
    aws_smoke_test.run_smoke(REGION, real=False)
    out = capsys.readouterr().out
    assert "s3_roundtrip" in out and "glue_register" in out
    # Athena and Step Functions are simulated in Moto mode.
    assert "(simulated)" in out


def test_property_36_cleanup_runs_after_a_step_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from moto import mock_aws

    with mock_aws():
        session = boto3.session.Session()
        tester = SmokeTester(session, REGION, real=False)

        def boom() -> object:
            raise RuntimeError("injected glue failure")

        monkeypatch.setattr(tester, "step_glue_register", boom)
        code = tester.run()
    out = capsys.readouterr().out
    assert code == 1  # a failed step forces non-zero
    assert "0 survived" in out  # cleanup still ran


def test_property_40_real_path_refuses_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoCredsSession:
        def get_credentials(self) -> None:
            return None

    code = aws_smoke_test.run_smoke(REGION, real=True, session=NoCredsSession())  # type: ignore[arg-type]
    assert code == 1


def test_main_rejects_out_of_range_options() -> None:
    assert aws_smoke_test.main(["--sfn-timeout", "5"]) == 2
    assert aws_smoke_test.main(["--scan-limit", "100"]) == 2
    assert aws_smoke_test.main(["--region", "BAD"]) == 2
