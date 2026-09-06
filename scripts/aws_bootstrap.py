"""One-command bootstrap: empty account to verified stack.

Feature: aws-stage1-foundation, design 3.7.2.

Chains preflight, CDK bootstrap, budget deploy, data-stack deploy, and the smoke
test, in order, stopping at the first failure. Every mutating step is gated
behind a confirmation naming the account, region, and stacks; ``--assume-yes``
suppresses the prompt for unattended runs.

    make hackathon-bootstrap              # prompts for confirmation
    make hackathon-bootstrap ASSUME_YES=1 # unattended

This module does not deploy anything itself in Stage 1 tests: the data stack is a
Stage 2 delivery, so the step list reports a configuration error naming Stage 2
rather than silently succeeding with four steps. The 15-minute budget and real
cdk bootstrap/deploy behaviour are verified in a Stage 2 rehearsal, not here.
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class StepStatus(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    NOT_RUN = "not-run"


@dataclass
class BootstrapStep:
    name: str
    detect: Callable[[], bool]  # True when already satisfied
    run: Callable[[], int]  # returns an exit code


@dataclass
class StepReport:
    name: str
    status: StepStatus
    elapsed_seconds: int


# The ordered five steps. `data_stack_deploy` is a Stage 2 delivery.
DATA_STACK_STEP = "data_stack_deploy"


class BootstrapError(Exception):
    """The bootstrap cannot proceed (e.g. a required stack is undefined)."""


def default_steps(*, data_stack_available: bool) -> list[BootstrapStep]:
    if not data_stack_available:
        raise BootstrapError(
            f"step {DATA_STACK_STEP!r} requires the Stage 2 data stack, which is "
            "not defined yet; bootstrap cannot complete in Stage 1"
        )
    return []  # populated in Stage 2


def confirm(
    account: str, region: str, stacks: list[str], *, assume_yes: bool, stdin_isatty: bool
) -> bool:
    print(f"About to deploy to account {account} in {region}.")
    print("Stacks: " + (", ".join(stacks) if stacks else "(none defined in Stage 1)"))
    if assume_yes:
        return True
    if not stdin_isatty:
        print("unattended execution requires ASSUME_YES=1", file=sys.stderr)
        return False
    response = input("Type 'yes' to proceed: ").strip()
    if response != "yes":
        print("cancelled", file=sys.stderr)
        return False
    return True


def run_bootstrap(
    steps: list[BootstrapStep],
    account: str,
    region: str,
    *,
    assume_yes: bool,
    stdin_isatty: bool,
) -> tuple[int, list[StepReport]]:
    stack_names = [s.name for s in steps]
    if not confirm(account, region, stack_names, assume_yes=assume_yes, stdin_isatty=stdin_isatty):
        return 1, []

    reports: list[StepReport] = []
    total_started = time.monotonic()
    for index, step in enumerate(steps):
        started = time.monotonic()
        if step.detect():
            elapsed = int(time.monotonic() - started)
            reports.append(StepReport(step.name, StepStatus.UNCHANGED, elapsed))
            print(f"{step.name}: unchanged ({elapsed}s)")
            continue
        code = step.run()
        elapsed = int(time.monotonic() - started)
        if code != 0:
            reports.append(StepReport(step.name, StepStatus.FAILED, elapsed))
            unexecuted = [s.name for s in steps[index + 1 :]]
            total = int(time.monotonic() - total_started)
            print(f"{step.name}: FAILED ({elapsed}s)")
            print(f"not executed: {', '.join(unexecuted) or '(none)'}")
            print(f"total elapsed: {total}s")
            return 1, reports
        reports.append(StepReport(step.name, StepStatus.CHANGED, elapsed))
        print(f"{step.name}: changed ({elapsed}s)")

    total = int(time.monotonic() - total_started)
    print("\nsummary:")
    for report in reports:
        print(f"  {report.name}: {report.status.value} ({report.elapsed_seconds}s)")
    print(f"total elapsed: {total}s")
    return 0, reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Empty account to verified stack")
    parser.add_argument("--assume-yes", action="store_true")
    parser.add_argument("--region", default="ap-northeast-1")
    parser.parse_args(argv)

    # Stage 1: the data stack is not defined, so the chain cannot complete.
    try:
        default_steps(data_stack_available=False)
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
