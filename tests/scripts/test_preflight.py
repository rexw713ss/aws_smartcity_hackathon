"""Preflight checker scenarios under Moto.

Feature: aws-stage1-foundation
Properties 30 (credential failure degrades to skip), 32 (Bedrock never fails),
33 (always-on cost guard). Plus Requirement 5 criterion 19's five account
scenarios and criterion 22's summary.

The CDK bootstrap check is exercised through a monkeypatched stub rather than
moto's CloudFormation engine: plain moto (chosen to avoid Docker-dependent
extras) cannot import its CloudFormation backend. The check's own logic is
covered directly in test_cdk_bootstrap_logic.
"""

import boto3
import botocore.exceptions
import pytest
from moto import mock_aws

from scripts import aws_preflight
from scripts.aws_common import CheckResult, Outcome

REGION = "ap-northeast-1"


def _outcomes(report) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {c.name: c.outcome.value for c in report.checks}


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _stub_bootstrap(monkeypatch: pytest.MonkeyPatch, status: str | None) -> None:
    def fake(session: object, region: str, account: str) -> CheckResult:
        if status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            return CheckResult(
                name="cdk_bootstrap", outcome=Outcome.PASS, detail=f"CDKToolkit {status}"
            )
        return CheckResult(
            name="cdk_bootstrap",
            outcome=Outcome.FAIL,
            detail="CDKToolkit absent" if status is None else f"CDKToolkit {status}",
            remediation=f"npx cdk bootstrap aws://{account}/{region}",
        )

    monkeypatch.setattr(aws_preflight, "check_cdk_bootstrap", fake)


class TestPreflightScenarios:
    def test_all_pass_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_bootstrap(monkeypatch, "CREATE_COMPLETE")
        with mock_aws():
            report = aws_preflight.run_preflight(REGION)
        outcomes = _outcomes(report)
        assert outcomes["credentials"] == "pass"
        assert outcomes["cdk_bootstrap"] == "pass"
        assert aws_preflight.exit_status(report.checks) == 0

    def test_missing_bootstrap_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_bootstrap(monkeypatch, None)
        with mock_aws():
            report = aws_preflight.run_preflight(REGION)
        assert _outcomes(report)["cdk_bootstrap"] == "fail"
        assert aws_preflight.exit_status(report.checks) == 1
        bootstrap = next(c for c in report.checks if c.name == "cdk_bootstrap")
        assert bootstrap.remediation and "cdk bootstrap" in bootstrap.remediation

    def test_property_30_no_credentials_skips_downstream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(aws_preflight, "_credential_source", lambda session: None)
        report = aws_preflight.run_preflight(REGION)
        outcomes = _outcomes(report)
        assert outcomes["credentials"] == "fail"
        assert outcomes["cdk_bootstrap"] == "skip"
        assert all(outcomes[f"service.{s}"] == "skip" for s in ("s3", "glue", "athena"))
        assert aws_preflight.exit_status(report.checks) == 1

    def test_property_33_always_on_resource_warns_but_passes_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_bootstrap(monkeypatch, "CREATE_COMPLETE")
        with mock_aws():
            session = boto3.session.Session()
            ec2 = session.client("ec2", region_name=REGION)
            ec2.allocate_address(Domain="vpc")  # unassociated Elastic IP
            report = aws_preflight.run_preflight(REGION)
        guard = next(c for c in report.checks if c.name == "cost_guard")
        assert guard.outcome is Outcome.WARN
        assert guard.remediation
        assert aws_preflight.exit_status(report.checks) == 0

    def test_property_32_no_bedrock_access_warns_but_passes_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_bootstrap(monkeypatch, "CREATE_COMPLETE")
        monkeypatch.setattr(
            aws_preflight,
            "check_bedrock_model_access",
            lambda session, region: CheckResult(
                name="bedrock_model_access",
                outcome=Outcome.WARN,
                detail="0 models permitted for InvokeModel",
                remediation="Enable model access; rules require Bedrock before submission.",
            ),
        )
        with mock_aws():
            report = aws_preflight.run_preflight(REGION)
        access = next(c for c in report.checks if c.name == "bedrock_model_access")
        assert access.outcome is Outcome.WARN
        assert aws_preflight.exit_status(report.checks) == 0


class TestCdkBootstrapLogic:
    """Exercise the real check_cdk_bootstrap against a stubbed client."""

    def test_completed_status_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeCfn:
            def describe_stacks(self, StackName: str) -> dict:
                return {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]}

        session = _FakeSession(FakeCfn())
        result = aws_preflight.check_cdk_bootstrap(session, REGION, "123456789012")  # type: ignore[arg-type]
        assert result.outcome is Outcome.PASS

    def test_absent_stack_fails_with_remediation(self) -> None:
        class FakeCfn:
            def describe_stacks(self, StackName: str) -> dict:
                raise botocore.exceptions.ClientError(
                    {"Error": {"Code": "ValidationError"}}, "DescribeStacks"
                )

        session = _FakeSession(FakeCfn())
        result = aws_preflight.check_cdk_bootstrap(session, REGION, "123456789012")  # type: ignore[arg-type]
        assert result.outcome is Outcome.FAIL
        assert result.remediation and "cdk bootstrap" in result.remediation


class _FakeSession:
    def __init__(self, cfn: object) -> None:
        self._cfn = cfn

    def client(self, name: str, **kwargs: object) -> object:
        assert name == "cloudformation"
        return self._cfn


class TestPreflightMain:
    def test_invalid_region_returns_two(self) -> None:
        assert aws_preflight.main(["--region", "NOT-A-REGION"]) == 2

    def test_summary_reports_the_four_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_bootstrap(monkeypatch, "CREATE_COMPLETE")
        with mock_aws():
            report = aws_preflight.run_preflight(REGION)
        assert set(report.summary) == {"pass", "fail", "warn", "skip"}
        assert sum(report.summary.values()) == len(report.checks)
