"""Diagnose Bedrock access: what is listed, what is invokable, and why not.

Answers the question "can we actually use this model?" with a real Converse
call, because listing a model proves nothing — a model can appear in
``list_foundation_models`` while access is ungranted, region-blocked, or only
reachable through a cross-region inference profile.

    uv run python -m scripts.bedrock_check
    uv run python -m scripts.bedrock_check --region us-east-1
    uv run python -m scripts.bedrock_check --model anthropic.claude-sonnet-4-5-20250929-v1:0
    uv run python -m scripts.bedrock_check --json

Exits non-zero when no candidate model answers, so it works as a smoke test.

Newer Anthropic models are frequently not offered on demand and must be called
through an inference profile whose id carries a geography prefix
(``us.anthropic.…``). Each candidate is therefore probed both ways before being
reported as unavailable.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

import boto3
import botocore.exceptions

_DEFAULT_REGION = "us-east-1"
_DEFAULT_PROMPT = "Reply with the single word: OK"

# Probed in preference order when no --model is supplied. Anthropic ids
# discovered on the account are appended automatically.
_CANDIDATES = (
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-micro-v1:0",
    "meta.llama3-70b-instruct-v1:0",
)

# Geography prefixes used by cross-region inference profiles.
_PROFILE_PREFIXES = ("us.", "apac.", "eu.")


@dataclass
class Probe:
    """The outcome of one invocation attempt."""

    model_id: str
    ok: bool
    invoked_as: str | None = None
    text: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class Report:
    account: str | None = None
    principal: str | None = None
    region: str = _DEFAULT_REGION
    anthropic_listed: list[str] = field(default_factory=list)
    on_demand_text: list[str] = field(default_factory=list)
    inference_profiles: list[str] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)


def _identity(region: str, report: Report) -> None:
    try:
        who = boto3.client("sts", region_name=region).get_caller_identity()
        report.account = who.get("Account")
        report.principal = who.get("Arn")
    except botocore.exceptions.BotoCoreError as exc:
        report.principal = f"unavailable: {type(exc).__name__}"
    except botocore.exceptions.ClientError as exc:
        report.principal = f"unavailable: {_code(exc)}"


def _catalogue(region: str, report: Report) -> None:
    """Record what the account can see, which is not the same as can use."""
    client = boto3.client("bedrock", region_name=region)
    try:
        summaries = client.list_foundation_models()["modelSummaries"]
    except botocore.exceptions.ClientError as exc:
        report.anthropic_listed = [f"list_foundation_models denied: {_code(exc)}"]
        return

    for summary in summaries:
        model_id = str(summary.get("modelId", ""))
        if str(summary.get("providerName", "")).lower() == "anthropic":
            report.anthropic_listed.append(model_id)
        outputs = summary.get("outputModalities") or []
        if "ON_DEMAND" in (summary.get("inferenceTypesSupported") or []) and "TEXT" in outputs:
            report.on_demand_text.append(model_id)

    try:
        profiles = client.list_inference_profiles()["inferenceProfileSummaries"]
        report.inference_profiles = [str(p.get("inferenceProfileId", "")) for p in profiles]
    except botocore.exceptions.ClientError as exc:
        report.inference_profiles = [f"list_inference_profiles denied: {_code(exc)}"]
    except AttributeError:  # pragma: no cover - older botocore
        report.inference_profiles = ["unsupported by the installed botocore"]


def _converse(client: object, model_id: str, prompt: str) -> Probe:
    """One real invocation. Success here is the only proof that matters."""
    try:
        response = client.converse(  # type: ignore[attr-defined]
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 20, "temperature": 0.0},
        )
    except botocore.exceptions.ClientError as exc:
        return Probe(
            model_id=model_id,
            ok=False,
            error_code=_code(exc),
            error_message=str(exc.response.get("Error", {}).get("Message", ""))[:200],
        )
    except botocore.exceptions.BotoCoreError as exc:
        return Probe(model_id=model_id, ok=False, error_code=type(exc).__name__)

    usage = response.get("usage", {})
    blocks = response["output"]["message"]["content"]
    return Probe(
        model_id=model_id,
        ok=True,
        invoked_as=model_id,
        text="".join(block.get("text", "") for block in blocks).strip(),
        input_tokens=usage.get("inputTokens"),
        output_tokens=usage.get("outputTokens"),
    )


def _probe(client: object, model_id: str, prompt: str, profiles: list[str]) -> Probe:
    """Try the plain id, then any inference-profile form that exists."""
    direct = _converse(client, model_id, prompt)
    if direct.ok:
        return direct

    for prefix in _PROFILE_PREFIXES:
        candidate = f"{prefix}{model_id}"
        # Only worth a call when the account actually exposes that profile, or
        # when profile listing was denied and we cannot know.
        listable = any(candidate == profile for profile in profiles)
        if not listable and profiles and not profiles[0].startswith("list_inference_profiles"):
            continue
        attempt = _converse(client, candidate, prompt)
        if attempt.ok:
            attempt.model_id = model_id
            attempt.invoked_as = candidate
            return attempt

    return direct


def _code(exc: botocore.exceptions.ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", "Unknown"))


def _print_human(report: Report) -> None:
    print(f"account   : {report.account}")
    print(f"principal : {report.principal}")
    print(f"region    : {report.region}")

    print("\nAnthropic models listed on this account:")
    if report.anthropic_listed:
        for model_id in report.anthropic_listed:
            print(f"  - {model_id}")
    else:
        print("  (none — no Claude/Sonnet model is offered to this account in this region)")

    print(f"\nOn-demand text models listed: {len(report.on_demand_text)}")
    for model_id in report.on_demand_text:
        print(f"  - {model_id}")

    print("\nInference profiles:")
    if report.inference_profiles:
        for profile in report.inference_profiles:
            print(f"  - {profile}")
    else:
        print("  (none)")

    print("\nInvocation probes (a real Converse call each):")
    for probe in report.probes:
        if probe.ok:
            through = (
                "" if probe.invoked_as == probe.model_id else f" (via profile {probe.invoked_as})"
            )
            print(
                f"  PASS  {probe.model_id}{through}"
                f" -> {probe.text!r} in={probe.input_tokens} out={probe.output_tokens}"
            )
        else:
            print(f"  FAIL  {probe.model_id}  {probe.error_code}: {probe.error_message or ''}")

    working = [probe for probe in report.probes if probe.ok]
    print()
    if working:
        print(f"USABLE NOW: {', '.join(probe.invoked_as or probe.model_id for probe in working)}")
    else:
        print("NOTHING USABLE. Common causes, in the order worth checking:")
        print("  - AccessDeniedException  : model access not granted, or the region is")
        print("                             blocked by a service control policy")
        print("  - ValidationException    : the model id does not exist, or needs an")
        print("                             inference profile rather than a plain id")
        print("  - ResourceNotFound       : not offered in this region")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=_DEFAULT_REGION)
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="probe only these ids (repeatable)",
    )
    parser.add_argument("--prompt", default=_DEFAULT_PROMPT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = Report(region=args.region)
    _identity(args.region, report)
    _catalogue(args.region, report)

    candidates: list[str] = list(args.model) or [
        *_CANDIDATES,
        # Anything Anthropic the account exposes that is not already listed.
        *(m for m in report.anthropic_listed if m not in _CANDIDATES and ":" in m),
    ]

    runtime = boto3.client("bedrock-runtime", region_name=args.region)
    profiles = [p for p in report.inference_profiles]
    for model_id in candidates:
        report.probes.append(_probe(runtime, model_id, args.prompt, profiles))

    if args.json:
        print(
            json.dumps(
                {**asdict(report), "probes": [asdict(p) for p in report.probes]},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        _print_human(report)

    return 0 if any(probe.ok for probe in report.probes) else 1


if __name__ == "__main__":
    sys.exit(main())
