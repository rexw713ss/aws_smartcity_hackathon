"""Transform Lambda byte-identical output test.

Feature: aws-stage2-adapters, Requirement 6.

Invokes the Lambda handler on the employment_unfamiliar.csv fixture and asserts
the output matches what the local CLI produces for the same input.
"""

import json
from pathlib import Path

from adapters.aws.transform_lambda import handler
from youth_compass.ingestion.csv_profiler import profile_csv
from youth_compass.mapping.engine import analyze_mapping

FIXTURE = Path("tests/fixtures/employment_unfamiliar.csv")


def test_profile_action_matches_local() -> None:
    local = profile_csv(FIXTURE)
    lambda_result = handler({"action": "profile", "source_path": str(FIXTURE)}, None)
    assert lambda_result["status"] == "ok"
    assert lambda_result["result"] == json.loads(local.model_dump_json())


def test_analyze_action_matches_local() -> None:
    profile = profile_csv(FIXTURE)
    local = analyze_mapping(profile)
    lambda_result = handler({"action": "analyze", "source_path": str(FIXTURE)}, None)
    assert lambda_result["status"] == "ok"
    assert lambda_result["result"] == json.loads(local.model_dump_json())


def test_missing_source_path_returns_error() -> None:
    result = handler({"action": "profile"}, None)
    assert result["status"] == "error"


def test_unknown_action_returns_error() -> None:
    result = handler({"action": "unknown", "source_path": str(FIXTURE)}, None)
    assert result["status"] == "error"
