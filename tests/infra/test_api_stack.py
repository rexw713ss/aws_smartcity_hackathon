"""Synthesis assertions for the public API stack.

Feature: API deployment (lean MVP). These run offline with a placeholder account
and a stub Lambda asset, so they never read credentials or require the real
package to have been built.
"""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.environments import resolve_environment
from infra.errors import InfraConfigError
from infra.stacks import api as api_module
from infra.stacks.api import ApiStack, resolve_model_id, resolve_write_secret
from tests.infra.constants import PLACEHOLDER_ACCOUNT, PLACEHOLDER_REGION

STATE_MACHINE_ARN = (
    f"arn:aws:states:{PLACEHOLDER_REGION}:{PLACEHOLDER_ACCOUNT}:stateMachine:IngestionWorkflow"
)
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
FOUNDATION_MODEL_ID = "anthropic.claude-sonnet-4-6"
WRITE_SECRET = "a-sufficiently-long-secret"


@pytest.fixture
def template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Template:
    """Synthesize the stack against a stub asset directory."""
    asset = tmp_path / "api_lambda"
    asset.mkdir()
    (asset / "handler.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(api_module, "_API_ASSET", str(asset))

    app = cdk.App()
    config = resolve_environment("hackathon")
    stack = ApiStack(
        app,
        f"{config.stack_prefix}-Api",
        env_config=config,
        incoming_bucket_name="incoming-bucket",
        curated_bucket_name="curated-bucket",
        metadata_bucket_name="metadata-bucket",
        metadata_table_name="metadata-table",
        glue_database_name="youth_compass_hackathon",
        state_machine_arn=STATE_MACHINE_ARN,
        region=PLACEHOLDER_REGION,
        model_id=MODEL_ID,
        write_secret=WRITE_SECRET,
        env=cdk.Environment(account=PLACEHOLDER_ACCOUNT, region=PLACEHOLDER_REGION),
    )
    return Template.from_stack(stack)


class TestApiFunction:
    def test_runs_on_arm64_python_312(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Architectures": ["arm64"],
                "Runtime": "python3.12",
                "Handler": "apps.api.lambda_handler.handler",
            },
        )

    def test_data_root_points_at_a_writable_location(self, template: Template) -> None:
        # Regression: /var/task is read-only, so opening the SQLite catalog and
        # the local object store there fails at cold start.
        variables = self._api_environment(template)
        assert variables["YOUTH_COMPASS_DATA_ROOT"].startswith("/tmp/")
        assert variables["YOUTH_COMPASS_BAKED_DATA_ROOT"] == "/var/task/data"

    def _api_environment(self, template: Template) -> dict[str, str]:
        functions = template.find_resources("AWS::Lambda::Function")
        for function in functions.values():
            variables = function["Properties"].get("Environment", {}).get("Variables", {})
            if "YOUTH_COMPASS_DATA_ROOT" in variables:
                return dict(variables)
        raise AssertionError("no API function with a data root found")

    def test_carries_the_workflow_and_model_configuration(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Environment": {
                    "Variables": Match.object_like(
                        {
                            "YOUTH_COMPASS_STATE_MACHINE_ARN": STATE_MACHINE_ARN,
                            "YOUTH_COMPASS_MODEL__PROVIDER": "bedrock",
                            "YOUTH_COMPASS_MODEL__MODEL_ID": MODEL_ID,
                            "YOUTH_COMPASS_API__WRITE_SECRET": WRITE_SECRET,
                        }
                    )
                }
            },
        )

    def test_model_region_matches_the_stack_region(self, template: Template) -> None:
        # ap-northeast-1 is SCP-denied on the hackathon account, so the model
        # region must follow the deployment rather than an adapter default.
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Environment": {
                    "Variables": Match.object_like(
                        {"YOUTH_COMPASS_MODEL__REGION": PLACEHOLDER_REGION}
                    )
                }
            },
        )


class TestApiPermissions:
    def _statements(self, template: Template) -> list[dict]:
        policies = template.find_resources("AWS::IAM::Policy")
        found: list[dict] = []
        for policy in policies.values():
            found.extend(policy["Properties"]["PolicyDocument"]["Statement"])
        return found

    def test_can_resume_a_paused_approval(self, template: Template) -> None:
        # The gap a deployed API previously had: without SendTaskSuccess it
        # cannot resume a workflow waiting on a callback token.
        actions = {
            action
            for statement in self._statements(template)
            for action in _as_list(statement.get("Action"))
        }
        assert "states:SendTaskSuccess" in actions
        assert "states:SendTaskFailure" in actions

    def test_bedrock_access_is_scoped_to_the_configured_model(self, template: Template) -> None:
        bedrock = [
            statement
            for statement in self._statements(template)
            if any(a.startswith("bedrock:") for a in _as_list(statement.get("Action")))
        ]
        assert bedrock, "expected a bedrock statement"
        resources = json.dumps(bedrock[0]["Resource"])
        assert MODEL_ID in resources
        assert f"foundation-model/{FOUNDATION_MODEL_ID}" in resources
        assert f"foundation-model/{MODEL_ID}" not in resources
        assert bedrock[0]["Resource"] != "*"

    def test_curated_zone_is_read_only(self, template: Template) -> None:
        # The API serves curated data; only the workflow may publish it.
        curated_writes = [
            statement
            for statement in self._statements(template)
            if any(
                action in {"s3:PutObject", "s3:DeleteObject"}
                for action in _as_list(statement.get("Action"))
            )
            and "curated-bucket" in json.dumps(statement.get("Resource"))
        ]
        assert curated_writes == []

    def test_agent_can_query_only_its_athena_workgroup(self, template: Template) -> None:
        athena_statements = [
            statement
            for statement in self._statements(template)
            if "athena:StartQueryExecution" in _as_list(statement.get("Action"))
        ]
        assert len(athena_statements) == 1
        assert "workgroup/youth-compass-hackathon" in json.dumps(athena_statements[0]["Resource"])
        assert athena_statements[0]["Resource"] != "*"

    def test_athena_results_permissions_do_not_allow_delete(self, template: Template) -> None:
        metadata_statements = [
            statement
            for statement in self._statements(template)
            if "metadata-bucket" in json.dumps(statement.get("Resource"))
        ]
        actions = {
            action
            for statement in metadata_statements
            for action in _as_list(statement.get("Action"))
        }
        assert "s3:PutObject" in actions
        assert "s3:DeleteObject" not in actions


class TestHttpApi:
    def test_exposes_an_http_api_with_preflight(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            {
                "ProtocolType": "HTTP",
                "CorsConfiguration": Match.object_like(
                    {"AllowHeaders": ["Content-Type", "X-Youth-Compass-Token"]}
                ),
            },
        )

    def test_publishes_the_base_url_and_site_url(self, template: Template) -> None:
        outputs = template.find_outputs("*")
        assert "ApiBaseUrl" in outputs
        assert "SiteUrl" in outputs


class TestAthenaRuntime:
    def test_provisions_a_cost_capped_workgroup(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::Athena::WorkGroup",
            {
                "Name": "youth-compass-hackathon",
                "WorkGroupConfiguration": Match.object_like(
                    {
                        "BytesScannedCutoffPerQuery": 100 * 1024 * 1024,
                        "EnforceWorkGroupConfiguration": True,
                    }
                ),
            },
        )

    def test_lambda_receives_aws_observation_configuration(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Environment": {
                    "Variables": Match.object_like(
                        {
                            "YOUTH_COMPASS_CATALOG__PROVIDER": "glue",
                            "YOUTH_COMPASS_CATALOG__DATABASE": "youth_compass_hackathon",
                            "YOUTH_COMPASS_CATALOG__TABLE_NAME": "metadata-table",
                            "YOUTH_COMPASS_QUERY__PROVIDER": "athena",
                            "YOUTH_COMPASS_QUERY__WORKGROUP": "youth-compass-hackathon",
                            "YOUTH_COMPASS_QUERY__OUTPUT_BUCKET": "metadata-bucket",
                        }
                    )
                }
            },
        )


class TestStaticSite:
    def test_site_bucket_blocks_all_public_access(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            },
        )

    def test_distribution_redirects_to_https_and_serves_the_spa(self, template: Template) -> None:
        distributions = template.find_resources("AWS::CloudFront::Distribution")
        assert len(distributions) == 1
        config = next(iter(distributions.values()))["Properties"]["DistributionConfig"]
        assert config["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
        assert config["DefaultRootObject"] == "index.html"
        # Client-side routing: a deep link must not return CloudFront's error XML.
        rewritten = {
            response["ErrorCode"]: response["ResponsePagePath"]
            for response in config["CustomErrorResponses"]
        }
        assert rewritten == {403: "/index.html", 404: "/index.html"}


class TestResolvers:
    def test_write_secret_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTH_COMPASS_WRITE_SECRET", raising=False)

        with pytest.raises(InfraConfigError, match="write secret"):
            resolve_write_secret(None)

    def test_short_write_secret_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTH_COMPASS_WRITE_SECRET", raising=False)

        with pytest.raises(InfraConfigError, match="too short"):
            resolve_write_secret("short")

    def test_write_secret_falls_back_to_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_WRITE_SECRET", WRITE_SECRET)

        assert resolve_write_secret(None) == WRITE_SECRET

    def test_model_id_defaults_to_the_verified_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTH_COMPASS_MODEL_ID", raising=False)

        assert resolve_model_id(None) == MODEL_ID


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []
