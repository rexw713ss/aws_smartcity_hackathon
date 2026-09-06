"""Bootstrap and teardown drivers.

Feature: aws-stage1-foundation
Properties 28 (chain stops at first failure), 46 (confirmation gate),
47 (idempotence), 48 (per-step reporting).
"""

import random

from scripts import aws_bootstrap, aws_teardown
from scripts.aws_bootstrap import BootstrapStep, StepStatus, run_bootstrap

ACCOUNT = "123456789012"
REGION = "ap-northeast-1"


def _step(name: str, *, satisfied: bool, code: int) -> BootstrapStep:
    return BootstrapStep(name=name, detect=lambda: satisfied, run=lambda: code)


class TestConfirmationGate:
    def test_property_46_assume_yes_proceeds(self) -> None:
        steps = [_step("a", satisfied=True, code=0)]
        code, _reports = run_bootstrap(steps, ACCOUNT, REGION, assume_yes=True, stdin_isatty=False)
        assert code == 0

    def test_property_46_non_tty_without_assume_yes_refuses(self) -> None:
        steps = [_step("a", satisfied=False, code=0)]
        code, reports = run_bootstrap(steps, ACCOUNT, REGION, assume_yes=False, stdin_isatty=False)
        assert code == 1
        assert reports == []  # nothing ran

    def test_teardown_wrong_account_number_cancels(self) -> None:
        proceeded = aws_teardown.confirm_teardown(
            ACCOUNT,
            REGION,
            ["StackA"],
            responder=lambda _prompt: "000000000000",
            stdin_isatty=True,
            assume_yes=False,
        )
        assert proceeded is False

    def test_teardown_correct_account_number_proceeds(self) -> None:
        proceeded = aws_teardown.confirm_teardown(
            ACCOUNT,
            REGION,
            ["StackA"],
            responder=lambda _prompt: ACCOUNT,
            stdin_isatty=True,
            assume_yes=False,
        )
        assert proceeded is True


class TestIdempotence:
    def test_property_47_all_satisfied_reports_unchanged(self) -> None:
        steps = [
            _step("preflight", satisfied=True, code=0),
            _step("bootstrap", satisfied=True, code=0),
        ]
        code, reports = run_bootstrap(steps, ACCOUNT, REGION, assume_yes=True, stdin_isatty=False)
        assert code == 0
        assert all(r.status is StepStatus.UNCHANGED for r in reports)


class TestChainFailure:
    def test_property_28_chain_stops_at_first_failure(self) -> None:
        rng = random.Random(28)
        for _ in range(100):
            codes = [rng.choice([0, 0, 1]) for _ in range(4)]
            steps = [_step(f"s{i}", satisfied=False, code=c) for i, c in enumerate(codes)]
            code, reports = run_bootstrap(
                steps, ACCOUNT, REGION, assume_yes=True, stdin_isatty=False
            )
            first_fail = next((i for i, c in enumerate(codes) if c != 0), None)
            if first_fail is None:
                assert code == 0
                assert len(reports) == 4
            else:
                assert code == 1
                # Executed the prefix through and including the first failing step.
                assert len(reports) == first_fail + 1
                assert reports[-1].status is StepStatus.FAILED

    def test_property_48_each_step_reports_name_and_elapsed(self) -> None:
        steps = [_step("s0", satisfied=False, code=0), _step("s1", satisfied=False, code=0)]
        _code, reports = run_bootstrap(steps, ACCOUNT, REGION, assume_yes=True, stdin_isatty=False)
        assert [r.name for r in reports] == ["s0", "s1"]
        assert all(r.elapsed_seconds >= 0 for r in reports)


class TestStageOneStepList:
    def test_data_stack_absent_reports_stage_2(self) -> None:
        code = aws_bootstrap.main(["--assume-yes"])
        assert code == 1  # data stack undefined in Stage 1
