"""Forbidden-import guard.

Feature: aws-stage1-foundation, Property 4.

Requirement 1 criterion 7 and Requirement 9 criterion 4: no module under the
domain, application, or ports packages (nor anywhere under src/youth_compass/)
may import an infrastructure library. Uses ``ast`` so a name in a string or
comment cannot cause a false positive, and accumulates every violation rather
than stopping at the first.
"""

import ast
from pathlib import Path

import pytest

FORBIDDEN = {"boto3", "botocore", "aws_cdk", "constructs", "moto", "fastapi"}
SRC = Path(__file__).resolve().parents[2] / "src" / "youth_compass"


def _violations(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN or name.startswith("adapters."):
                    findings.append(f"{path.name}:{node.lineno}: imports {name}")
    return findings


def test_property_4_no_forbidden_imports_under_src() -> None:
    findings = _violations(SRC)
    assert not findings, "forbidden imports found:\n" + "\n".join(findings)


def test_property_4_accumulates_all_violations(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import boto3\nimport moto\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    findings = _violations(tmp_path)
    assert len(findings) == 3, findings
    joined = "\n".join(findings)
    assert "boto3" in joined and "moto" in joined and "fastapi" in joined


@pytest.mark.parametrize("package", ("domain", "application", "ports"))
def test_forbidden_imports_absent_per_seam_package(package: str) -> None:
    root = SRC / package
    if not root.exists():
        pytest.skip(f"{package} package not present")
    assert not _violations(root)
