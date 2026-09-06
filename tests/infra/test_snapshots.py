"""CloudFormation snapshot tests with template normalization.

Feature: aws-stage1-foundation, Property 25.

Raw CDK output embeds the construct-library version, so comparison runs on a
normalized template: drop CDKMetadata, the bootstrap-version parameter and rule,
and any aws:cdk:path metadata. Refresh with UPDATE_INFRA_SNAPSHOTS=1.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.infra.conftest import synth_budget_stack

ENVS = ("dev", "demo", "hackathon")
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _normalize(template: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(template))  # deep copy
    result.get("Resources", {}).pop("CDKMetadata", None)
    result.get("Parameters", {}).pop("BootstrapVersion", None)
    result.get("Rules", {}).pop("CheckBootstrapVersion", None)
    for resource in result.get("Resources", {}).values():
        metadata = resource.get("Metadata")
        if isinstance(metadata, dict):
            metadata.pop("aws:cdk:path", None)
            if not metadata:
                resource.pop("Metadata", None)
    for empty_key in ("Parameters", "Rules"):
        if empty_key in result and not result[empty_key]:
            result.pop(empty_key)
    return result


def _diff_paths(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Return the dotted paths where two JSON documents differ."""

    if isinstance(expected, dict) and isinstance(actual, dict):
        paths: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                paths.append(child)
            else:
                paths += _diff_paths(expected[key], actual[key], child)
        return paths
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [path]
        paths = []
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            paths += _diff_paths(e, a, f"{path}[{i}]")
        return paths
    return [] if expected == actual else [path]


def _snapshot_path(env_name: str) -> Path:
    return SNAPSHOT_DIR / f"YouthCompass-{env_name}-Budget.template.json"


@pytest.mark.parametrize("env_name", ENVS)
def test_property_25_synthesized_matches_committed_snapshot(env_name: str) -> None:
    actual = _normalize(synth_budget_stack(env_name).to_json())
    path = _snapshot_path(env_name)

    if os.environ.get("UPDATE_INFRA_SNAPSHOTS"):
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"refreshed snapshot for {env_name}")

    assert path.exists(), f"missing snapshot {path}; run UPDATE_INFRA_SNAPSHOTS=1"
    expected = json.loads(path.read_text(encoding="utf-8"))
    diffs = _diff_paths(expected, actual)
    assert not diffs, f"{env_name} template drifted at: " + ", ".join(diffs)


def test_property_25_diff_reporter_finds_planted_mutations() -> None:
    expected = {"Resources": {"B": {"Type": "AWS::Budgets::Budget", "Properties": {"X": 1}}}}
    actual = {"Resources": {"B": {"Type": "AWS::Budgets::Budget", "Properties": {"X": 2}}}}
    diffs = _diff_paths(expected, actual)
    assert diffs == ["Resources.B.Properties.X"]
