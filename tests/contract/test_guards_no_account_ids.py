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


def _py_files(*relative: str) -> list[Path]:
    files: list[Path] = []
    for rel in relative:
        base = ROOT / rel
        if base.exists():
            files.extend(sorted(base.rglob("*.py")))
    return files


def test_no_twelve_digit_account_id_under_scripts_and_infra() -> None:
    findings: list[str] = []
    for path in _py_files("scripts", "infra"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ACCOUNT_ID.search(line):
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
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ACCESS_KEY.search(line):
                findings.append(f"{rel}:{lineno}")  # value deliberately not recorded
    assert not findings, "access-key-shaped strings found at:\n" + "\n".join(findings)
