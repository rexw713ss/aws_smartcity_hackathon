"""LocalStack is inert with respect to the test suite.

Feature: aws-stage1-foundation, Property 56.

No collected test and no bootstrap step references the LocalStack host port or a
container start command, so the suite passes with no container runtime present.
"""

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


def test_compose_declares_free_tier_services_without_athena() -> None:
    spec = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    localstack = spec["services"]["localstack"]
    services = localstack["environment"]["SERVICES"].split(",")
    assert "athena" not in services
    assert set(services) == {"s3", "stepfunctions", "glue"}
    # Pinned tag, not floating latest.
    assert localstack["image"].endswith(":3.8.1")


def test_compose_declares_no_licence_or_auth_token() -> None:
    text = COMPOSE.read_text(encoding="utf-8").lower()
    for forbidden in (
        "localstack_auth_token",
        "localstack_api_key",
        "localstack-pro",
        "localstack/localstack-pro",
    ):
        assert forbidden not in text, forbidden


def test_property_56_no_test_references_localstack_port_or_start() -> None:
    findings: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name == "test_localstack_inert.py":
            continue  # this file legitimately mentions the port in assertions
        text = path.read_text(encoding="utf-8")
        if "4566" in text or "docker compose up" in text or "docker-compose up" in text:
            findings.append(str(path.relative_to(ROOT)))
    assert not findings, "tests reference the LocalStack runtime:\n" + "\n".join(findings)


def test_property_56_no_bootstrap_step_starts_the_container() -> None:
    text = (ROOT / "scripts" / "aws_bootstrap.py").read_text(encoding="utf-8")
    assert "4566" not in text
    assert "localstack" not in text.lower()
    # confirm it parses (sanity, not a runtime dependency)
    ast.parse(text)
