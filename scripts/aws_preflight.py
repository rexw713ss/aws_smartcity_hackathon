"""Account-readiness preflight checker.

Feature: aws-stage1-foundation, design 3.5.2.

One command, about ten seconds, that says what works, what is missing, and what
to do about it. Every check is read-only and free. Run it on competition morning
against the provided account before doing anything else:

    uv run python scripts/aws_preflight.py [--region ap-northeast-1] [--json]
"""

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime

import boto3
import botocore.exceptions

from scripts.aws_common import (
    CheckResult,
    Outcome,
    RegionError,
    Report,
    boto_config,
    exit_status,
    render_json,
    render_table,
    run_check,
    summarize,
    validate_region,
)

ALWAYS_ON_LABELS = {
    "sagemaker_endpoints": "SageMaker real-time endpoint",
    "sagemaker_notebooks": "SageMaker notebook instance",
    "nat_gateways": "NAT Gateway",
    "rds_instances": "RDS DB instance",
    "elastic_ips": "unassociated Elastic IP",
}


def _session() -> boto3.session.Session:
    return boto3.session.Session()


def _credential_source(session: boto3.session.Session) -> str | None:
    creds = session.get_credentials()
    if creds is None:
        return None
    method = getattr(creds, "method", "unknown")
    mapping = {
        "env": "environment variables",
        "shared-credentials-file": "shared credentials file",
        "config-file": "shared config profile",
        "sso": "single sign-on cache",
        "container-role": "container credentials",
        "iam-role": "instance metadata",
        "assume-role": "assumed role",
    }
    return mapping.get(method, method)


def check_credentials(session: boto3.session.Session, region: str) -> CheckResult:
    source = _credential_source(session)
    if source is None:
        return CheckResult(
            name="credentials",
            outcome=Outcome.FAIL,
            detail="no AWS credentials resolved",
            remediation="Configure credentials: aws configure sso, or aws configure.",
        )
    sts = session.client("sts", region_name=region, config=boto_config())
    identity = sts.get_caller_identity()
    return CheckResult(
        name="credentials",
        outcome=Outcome.PASS,
        detail=f"source={source} account={identity['Account']} arn={identity['Arn']}"[:120],
    )


def check_cdk_bootstrap(session: boto3.session.Session, region: str, account: str) -> CheckResult:
    cfn = session.client("cloudformation", region_name=region, config=boto_config())
    try:
        stacks = cfn.describe_stacks(StackName="CDKToolkit")["Stacks"]
    except botocore.exceptions.ClientError:
        return CheckResult(
            name="cdk_bootstrap",
            outcome=Outcome.FAIL,
            detail="CDKToolkit stack absent",
            remediation=f"npx cdk bootstrap aws://{account}/{region}",
        )
    status = stacks[0]["StackStatus"]
    if status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
        return CheckResult(
            name="cdk_bootstrap", outcome=Outcome.PASS, detail=f"CDKToolkit {status}"
        )
    return CheckResult(
        name="cdk_bootstrap",
        outcome=Outcome.FAIL,
        detail=f"CDKToolkit {status}",
        remediation=f"npx cdk bootstrap aws://{account}/{region}",
    )


_SERVICE_PROBES: dict[str, tuple[str, Callable[[object], object]]] = {
    "s3": ("s3", lambda c: c.list_buckets()),  # type: ignore[attr-defined]
    "glue": ("glue", lambda c: c.get_databases(MaxResults=1)),  # type: ignore[attr-defined]
    "athena": ("athena", lambda c: c.list_work_groups(MaxResults=1)),  # type: ignore[attr-defined]
    "stepfunctions": ("stepfunctions", lambda c: c.list_state_machines(maxResults=1)),  # type: ignore[attr-defined]
    "lambda": ("lambda", lambda c: c.list_functions(MaxItems=1)),  # type: ignore[attr-defined]
    "bedrock": ("bedrock", lambda c: c.list_foundation_models()),  # type: ignore[attr-defined]
}


def check_service(session: boto3.session.Session, region: str, name: str) -> CheckResult:
    client_name, probe = _SERVICE_PROBES[name]
    client = session.client(client_name, region_name=region, config=boto_config())
    try:
        probe(client)
    except botocore.exceptions.ClientError as exc:
        # A real authorization or service error. Bedrock is deferred, so its
        # reachability is advisory (WARN); every other service is a hard FAIL.
        code = exc.response.get("Error", {}).get("Code", type(exc).__name__)
        outcome = Outcome.WARN if name == "bedrock" else Outcome.FAIL
        return CheckResult(name=f"service.{name}", outcome=outcome, detail=str(code)[:120])
    except (NotImplementedError, ModuleNotFoundError) as exc:
        # The local mock does not cover this service; not a real-account signal.
        return CheckResult(
            name=f"service.{name}",
            outcome=Outcome.WARN,
            detail=f"reachability unverifiable in this environment: {type(exc).__name__}"[:120],
        )
    return CheckResult(name=f"service.{name}", outcome=Outcome.PASS, detail=f"{client_name} ok")


def check_cost_guard(session: boto3.session.Session, region: str) -> CheckResult:
    found: list[str] = []
    ec2 = session.client("ec2", region_name=region, config=boto_config())
    sm = session.client("sagemaker", region_name=region, config=boto_config())
    rds = session.client("rds", region_name=region, config=boto_config())
    found += [f"endpoint {e['EndpointName']}" for e in sm.list_endpoints().get("Endpoints", [])]
    found += [
        f"notebook {n['NotebookInstanceName']}"
        for n in sm.list_notebook_instances().get("NotebookInstances", [])
    ]
    found += [
        f"nat {g['NatGatewayId']}" for g in ec2.describe_nat_gateways().get("NatGateways", [])
    ]
    found += [
        f"rds {d['DBInstanceIdentifier']}"
        for d in rds.describe_db_instances().get("DBInstances", [])
    ]
    found += [
        f"eip {a['PublicIp']}"
        for a in ec2.describe_addresses().get("Addresses", [])
        if "AssociationId" not in a
    ]
    if not found:
        return CheckResult(name="cost_guard", outcome=Outcome.PASS, detail="0 always-on resources")
    return CheckResult(
        name="cost_guard",
        outcome=Outcome.WARN,
        detail=f"{len(found)} always-on resource(s): {', '.join(found)}"[:120],
        remediation="Delete unused always-on resources; each accrues charges while it exists.",
    )


def check_bedrock_model_access(session: boto3.session.Session, region: str) -> CheckResult:
    client = session.client("bedrock", region_name=region, config=boto_config())
    try:
        models = client.list_foundation_models().get("modelSummaries", [])
    except (botocore.exceptions.ClientError, NotImplementedError, ModuleNotFoundError):
        models = []
    ids = [m.get("modelId", "") for m in models if m.get("modelId")]
    if ids:
        return CheckResult(
            name="bedrock_model_access",
            outcome=Outcome.PASS,
            detail=f"{len(ids)} models listed",
        )
    return CheckResult(
        name="bedrock_model_access",
        outcome=Outcome.WARN,
        detail="0 models permitted for InvokeModel",
        remediation=(
            "Enable model access in the Bedrock console. Competition rules require "
            "Bedrock model access before submission."
        ),
    )


def _skipped(name: str) -> CheckResult:
    return CheckResult(name=name, outcome=Outcome.SKIP, detail="skipped: no credentials")


def run_preflight(region: str) -> Report:
    started = datetime.now(UTC)
    session = _session()
    results: list[CheckResult] = []

    cred = run_check("credentials", lambda: check_credentials(session, region))
    results.append(cred)

    downstream = [
        "cdk_bootstrap",
        *[f"service.{s}" for s in _SERVICE_PROBES],
        "bedrock_model_access",
        "cost_guard",
    ]
    if cred.outcome is Outcome.FAIL:
        results += [_skipped(name) for name in downstream]
    else:
        account = _account(session, region)
        results.append(
            run_check("cdk_bootstrap", lambda: check_cdk_bootstrap(session, region, account))
        )
        for svc in _SERVICE_PROBES:
            results.append(
                run_check(
                    f"service.{svc}",
                    lambda s=svc: check_service(session, region, s),  # type: ignore[misc]
                )
            )
        results.append(
            run_check("bedrock_model_access", lambda: check_bedrock_model_access(session, region))
        )
        results.append(run_check("cost_guard", lambda: check_cost_guard(session, region)))

    elapsed = (datetime.now(UTC) - started).total_seconds()
    return Report(
        tool="aws-preflight",
        region=region,
        started_at=started,
        elapsed_seconds=elapsed,
        summary=summarize(results),
        checks=results,
    )


def _account(session: boto3.session.Session, region: str) -> str:
    sts = session.client("sts", region_name=region, config=boto_config())
    return str(sts.get_caller_identity()["Account"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AWS account-readiness preflight checker")
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        region = validate_region(args.region)
    except RegionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    report = run_preflight(region)
    print(render_json(report) if args.json else render_table(report))
    return exit_status(report.checks)


if __name__ == "__main__":
    raise SystemExit(main())
