"""Tear down deployed stacks, behind an account-number confirmation.

Feature: aws-stage1-foundation, design 3.7.2.

Destructive, so the operator must type the 12-digit account number, obtained
from GetCallerIdentity at runtime rather than a literal, keeping the hard-coded
account-id guard clean.
"""

import argparse
import sys
from collections.abc import Callable

import boto3

from scripts.aws_common import boto_config, validate_region


def _account(region: str, session: boto3.session.Session) -> str:
    sts = session.client("sts", region_name=region, config=boto_config())
    return str(sts.get_caller_identity()["Account"])


def confirm_teardown(
    account: str,
    region: str,
    stacks: list[str],
    *,
    responder: Callable[[str], str],
    stdin_isatty: bool,
    assume_yes: bool,
) -> bool:
    print(f"About to DESTROY stacks in account {account} ({region}).")
    print("Stacks: " + (", ".join(stacks) if stacks else "(none)"))
    if assume_yes:
        return True
    if not stdin_isatty:
        print("unattended teardown requires --assume-yes", file=sys.stderr)
        return False
    response = responder(f"Type the account number {account} to confirm: ").strip()
    if response != account:
        print("cancelled", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Destroy deployed stacks")
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--assume-yes", action="store_true")
    args = parser.parse_args(argv)

    region = validate_region(args.region)
    session = boto3.session.Session()
    if session.get_credentials() is None:
        print("teardown requires resolvable AWS credentials", file=sys.stderr)
        return 1
    account = _account(region, session)
    stacks: list[str] = []  # Stage 1 deploys nothing; Stage 2 populates this.
    ok = confirm_teardown(
        account,
        region,
        stacks,
        responder=input,
        stdin_isatty=sys.stdin.isatty(),
        assume_yes=args.assume_yes,
    )
    if not ok:
        return 1
    print("nothing to destroy in Stage 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
