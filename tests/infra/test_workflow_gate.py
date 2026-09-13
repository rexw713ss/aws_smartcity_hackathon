"""The ingestion workflow's confidence gate must never crash the execution.

Regression coverage for a live failure: uploading a CSV whose grain could not be
inferred made the whole execution fail with States.Runtime, leaving the object
neither published nor quarantined.

The analyze handler reports its own failures inside the payload (``status:
error``, no ``result`` key) and returns successfully, so the Lambda-level
States.ALL catch does not fire. The gate has to cope with a payload that has no
confidence value at all.
"""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from infra.environments import resolve_environment
from infra.stacks import workflow as workflow_module
from infra.stacks.workflow import WorkflowStack
from tests.infra.constants import PLACEHOLDER_ACCOUNT, PLACEHOLDER_REGION

_CONFIDENCE_PATH = "$.analysis.Payload.result.validation.overall_confidence"


@pytest.fixture
def definition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Synthesize the workflow and return the parsed state-machine definition."""
    asset = tmp_path / "transform_lambda"
    asset.mkdir()
    (asset / "handler.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(workflow_module, "_LAMBDA_ASSET", str(asset))

    app = cdk.App()
    config = resolve_environment("hackathon")
    stack = WorkflowStack(
        app,
        f"{config.stack_prefix}-Workflow",
        env_config=config,
        incoming_bucket_name="incoming",
        standardized_bucket_name="standardized",
        curated_bucket_name="curated",
        quarantined_bucket_name="quarantined",
        forecasts_bucket_name="forecasts",
        metadata_table_name="metadata",
        glue_database_name="youth_compass_hackathon",
        region=PLACEHOLDER_REGION,
        env=cdk.Environment(account=PLACEHOLDER_ACCOUNT, region=PLACEHOLDER_REGION),
    )
    template = Template.from_stack(stack)
    machines = template.find_resources("AWS::StepFunctions::StateMachine")
    body = next(iter(machines.values()))["Properties"]["DefinitionString"]
    # The definition is a Fn::Join of literal fragments and token references;
    # only the literal parts carry the choice structure.
    if isinstance(body, dict):
        parts = body["Fn::Join"][1]
        body = "".join(part for part in parts if isinstance(part, str))
    return json.loads(body)


def _gate(definition: dict) -> dict:
    return definition["States"]["ConfidenceGate"]


class TestConfidenceGate:
    def test_a_failed_analysis_routes_to_quarantine(self, definition: dict) -> None:
        choices = _gate(definition)["Choices"]
        error_branch = [
            choice
            for choice in choices
            if choice.get("Variable") == "$.analysis.Payload.status"
            and choice.get("StringEquals") == "error"
        ]
        assert error_branch, "no branch handles an analyze payload reporting status=error"
        assert error_branch[0]["Next"] == "Quarantine"

    def test_confidence_is_checked_for_presence_before_comparison(self, definition: dict) -> None:
        # Comparing a missing path is what produced States.Runtime in production.
        serialized = json.dumps(_gate(definition))
        assert '"IsPresent": true' in serialized
        assert _CONFIDENCE_PATH in serialized

    def test_high_confidence_publishes(self, definition: dict) -> None:
        choices = _gate(definition)["Choices"]
        publishing = [choice for choice in choices if choice.get("Next") == "Publish"]
        assert publishing, "no branch publishes"
        assert "0.95" in json.dumps(publishing[0])

    def test_unknown_confidence_falls_through_to_human_review(self, definition: dict) -> None:
        # Not a crash, and not a silent publish.
        assert _gate(definition)["Default"] == "AwaitApproval"


class TestForecastRefresh:
    def test_a_publish_is_followed_by_a_forecast_refresh(self, definition: dict) -> None:
        states = definition["States"]
        assert states["Publish"]["Next"] == "RefreshForecast"
        payload = states["RefreshForecast"]["Parameters"]["Payload"]
        assert payload["published.$"] == "$.publish.Payload.published"

    def test_a_refresh_failure_never_fails_the_ingestion(self, definition: dict) -> None:
        (catch,) = definition["States"]["RefreshForecast"]["Catch"]
        assert catch["ErrorEquals"] == ["States.ALL"]
        assert definition["States"][catch["Next"]]["Type"] == "Pass"
