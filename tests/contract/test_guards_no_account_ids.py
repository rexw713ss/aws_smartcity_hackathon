"""Hard-coded account-id and secret guards.

Feature: aws-stage1-foundation, Property 18.

Requirement 9 criterion 8: no literal 12-digit AWS account id under scripts/ or
infra/. Requirement 9 criterion 9 / 10.5: no credential-shaped string and no real
account id in tracked files, and configs/aws.example.yaml carries placeholders
only. Findings report path and line, never the matched value.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
ACCESS_KEY = re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")


# Generated build output, not source. `cdk synth` stages Lambda assets here,
# bundling third-party wheels whose data tables contain 12-digit runs; scanning
# them reports vendored library code rather than anything we wrote. The mypy
# configuration excludes this directory for the same reason.
_GENERATED_DIRECTORIES = ("cdk.out", "build", "__pycache__")


# AWS-owned accounts that publish public managed layers. These are documented
# addresses of someone else's account, not ours: they are how a layer ARN is
# constructed at all, they carry no access to this deployment, and pulling them
# into configuration would only move a published constant somewhere less
# reviewable. The guard exists to stop *our* account id from being committed, so
# each of these is allowlisted individually with the layer it identifies.
_PUBLIC_AWS_LAYER_ACCOUNTS = {
    # awslabs/aws-lambda-web-adapter, us-east-1 layer publisher.
    "753240598075",
}


def _is_generated(path: Path) -> bool:
    return any(part in _GENERATED_DIRECTORIES for part in path.parts)


def _py_files(*relative: str) -> list[Path]:
    files: list[Path] = []
    for rel in relative:
        base = ROOT / rel
        if base.exists():
            files.extend(sorted(p for p in base.rglob("*.py") if not _is_generated(p)))
    return files


def test_no_twelve_digit_account_id_under_scripts_and_infra() -> None:
    findings: list[str] = []
    for path in _py_files("scripts", "infra"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            found = set(ACCOUNT_ID.findall(line))
            if found - _PUBLIC_AWS_LAYER_ACCOUNTS:
                findings.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not findings, "12-digit account ids found at:\n" + "\n".join(findings)


def test_aws_example_config_is_placeholder_only() -> None:
    text = (ROOT / "configs" / "aws.example.yaml").read_text(encoding="utf-8")
    assert not ACCOUNT_ID.search(text), "aws.example.yaml contains a 12-digit id"
    assert not ACCESS_KEY.search(text), "aws.example.yaml contains an access key id"
    assert "PLACEHOLDER" in text


def test_secret_scan_over_tracked_files() -> None:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    findings: list[str] = []
    for rel in result.stdout.splitlines():
        path = ROOT / rel
        if not path.is_file() or path.suffix in {".png", ".jpg", ".gif", ".webp"}:
            continue
        # Test files legitimately contain AWS's documentation example key
        # (AKIAIOSFODNN7EXAMPLE) to exercise the redaction helper; real secrets
        # never live under tests/, so exclude it as the account-id scan does.
        if rel.startswith("tests/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ACCESS_KEY.search(line):
                findings.append(f"{rel}:{lineno}")  # value deliberately not recorded
    assert not findings, "access-key-shaped strings found at:\n" + "\n".join(findings)
