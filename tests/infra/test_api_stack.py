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
from infra.stacks import api as api_module
from infra.stacks.api import ApiStack, resolve_model_id
from tests.infra.constants import PLACEHOLDER_ACCOUNT, PLACEHOLDER_REGION

STATE_MACHINE_ARN = (
    f"arn:aws:states:{PLACEHOLDER_REGION}:{PLACEHOLDER_ACCOUNT}:stateMachine:IngestionWorkflow"
)
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
FOUNDATION_MODEL_ID = "anthropic.claude-sonnet-4-6"


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
        forecasts_bucket_name="forecasts-bucket",
        metadata_table_name="metadata-table",
        glue_database_name="youth_compass_hackathon",
        athena_workgroup_name="youthcompass-analytics",
        state_machine_arn=STATE_MACHINE_ARN,
        region=PLACEHOLDER_REGION,
        model_id=MODEL_ID,
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
                "Handler": "run.sh",
            },
        )

    def test_concurrency_is_reserved_so_a_burst_cannot_run_unbounded(
        self, template: Template
    ) -> None:
        template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {"ReservedConcurrentExecutions": api_module._API_RESERVED_CONCURRENCY}
            ),
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
                            "YOUTH_COMPASS_API__WRITE_SECRET_ARN": Match.any_value(),
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

    def test_api_is_restricted_to_the_approved_source_ips(self, template: Template) -> None:
        variables = self._api_environment(template)
        assert variables["YOUTH_COMPASS_ALLOWED_SOURCE_IPS"].split(",") == list(
            api_module._ALLOWED_SOURCE_IPS
        )


class TestSiteIpAllowlist:
    def test_cloudfront_runs_the_ip_allowlist_on_every_viewer_request(
        self, template: Template
    ) -> None:
        template.has_resource_properties(
            "AWS::CloudFront::Function",
            {
                "FunctionConfig": Match.object_like(
                    {"Runtime": "cloudfront-js-2.0", "Comment": Match.string_like_regexp("IP")}
                ),
                "FunctionCode": Match.string_like_regexp("60\\.250\\.71\\.45"),
            },
        )
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "DefaultCacheBehavior": Match.object_like(
                        {
                            "FunctionAssociations": [
                                Match.object_like({"EventType": "viewer-request"})
                            ]
                        }
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

    def test_forecast_is_read_from_s3_without_write_access(self, template: Template) -> None:
        variables = TestApiFunction()._api_environment(template)
        assert variables["YOUTH_COMPASS_FORECAST__PROVIDER"] == "s3"
        assert variables["YOUTH_COMPASS_FORECAST__BUCKET"] == "forecasts-bucket"
        assert variables["YOUTH_COMPASS_FORECAST__PREFIX"] == "population/"
        forecast_statements = [
            statement
            for statement in self._statements(template)
            if "forecasts-bucket" in json.dumps(statement.get("Resource"))
        ]
        actions = {
            action
            for statement in forecast_statements
            for action in _as_list(statement.get("Action"))
        }
        assert "s3:GetObject*" in actions
        assert not {"s3:PutObject", "s3:DeleteObject*", "s3:DeleteObject"} & actions
        assert "population/*" in json.dumps([item["Resource"] for item in forecast_statements])

    def test_can_query_athena_but_not_mutate_the_catalog(self, template: Template) -> None:
        actions = {
            action
            for statement in self._statements(template)
            for action in _as_list(statement.get("Action"))
        }
        # The acceptance test requires the API role to run queries...
        assert "athena:StartQueryExecution" in actions
        assert "glue:GetTable" in actions
        # ...but never to create, drop, or alter tables.
        for forbidden in ("glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"):
            assert forbidden not in actions

    def test_glue_read_is_scoped_to_the_one_database(self, template: Template) -> None:
        glue_reads = [
            statement
            for statement in self._statements(template)
            if any(a.startswith("glue:Get") for a in _as_list(statement.get("Action")))
        ]
        assert glue_reads, "expected a Glue read statement"
        resources = json.dumps(glue_reads[0]["Resource"])
        assert "youth_compass_hackathon" in resources
        assert '"*"' not in resources

    def test_athena_query_scoped_to_a_single_workgroup(self, template: Template) -> None:
        athena_statements = [
            statement
            for statement in self._statements(template)
            if "athena:StartQueryExecution" in _as_list(statement.get("Action"))
        ]
        assert len(athena_statements) == 1
        assert athena_statements[0]["Resource"] != "*"
        assert "workgroup/" in json.dumps(athena_statements[0]["Resource"])

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


class TestStreamingFunctionUrl:
    def test_exposes_a_streaming_function_url_with_cors(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::Lambda::Url",
            {
                "AuthType": "NONE",
                "InvokeMode": "RESPONSE_STREAM",
                "Cors": Match.object_like(
                    {"AllowHeaders": ["Content-Type", "X-Youth-Compass-Token"]}
                ),
            },
        )

    def test_cors_is_not_duplicated_by_the_fastapi_middleware(self, template: Template) -> None:
        functions = template.find_resources("AWS::Lambda::Function")
        api_environment = next(
            function["Properties"]["Environment"]["Variables"]
            for function in functions.values()
            if "YOUTH_COMPASS_DATA_ROOT"
            in function["Properties"].get("Environment", {}).get("Variables", {})
        )

        assert "YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS" not in api_environment

    def test_concurrency_is_capped_because_a_function_url_has_no_edge_throttle(
        self, template: Template
    ) -> None:
        # The copilot route is public and each call can invoke Bedrock twice, so
        # unbounded parallelism spends real money before the budget alarm fires.
        # A Function URL has no stage and therefore no request-rate throttle, so
        # reserved concurrency is the only cap available here. Asserting it keeps
        # someone from removing the cap while assuming an edge limit still exists.
        template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like(
                {"ReservedConcurrentExecutions": api_module._API_RESERVED_CONCURRENCY}
            ),
        )

    def test_publishes_the_base_url_and_site_url(self, template: Template) -> None:
        outputs = template.find_outputs("*")
        assert "ApiBaseUrl" in outputs
        assert "SiteUrl" in outputs


class TestAthenaRuntime:
    # The workgroup itself is owned by the DataStack (see test_data_stack.py);
    # the ApiStack consumes it by name. This asserts the API Lambda is handed
    # the AWS analytics configuration.
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
                            "YOUTH_COMPASS_QUERY__WORKGROUP": "youthcompass-analytics",
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


class TestWriteSecret:
    """The guard's secret is generated and read at runtime, never templated."""

    def test_the_secret_is_generated_by_secrets_manager(self, template: Template) -> None:
        template.has_resource_properties(
            "AWS::SecretsManager::Secret",
            Match.object_like({"GenerateSecretString": Match.any_value()}),
        )

    def test_no_literal_secret_appears_in_the_template(self, template: Template) -> None:
        # The whole point of the move: a synth-time value would be readable by
        # anyone who can read the template or the function configuration.
        rendered = json.dumps(template.to_json())
        # "SecretString" is the property carrying a supplied value;
        # "GenerateSecretString" (which the resource does use) is a different key.
        assert '"SecretString"' not in rendered
        assert 'YOUTH_COMPASS_API__WRITE_SECRET"' not in rendered

    def test_the_function_may_read_the_secret(self, template: Template) -> None:
        statements = [
            statement
            for policy in template.find_resources("AWS::IAM::Policy").values()
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]
            if "secretsmanager:GetSecretValue" in _as_list(statement.get("Action"))
        ]
        assert statements, "the API function cannot read its write secret"

    def test_the_secret_name_is_published_for_operators(self, template: Template) -> None:
        assert "WriteSecretName" in template.find_outputs("*")


class TestResolvers:
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


class TestConversationContext:
    def test_api_lambda_selects_the_durable_session_store(self, template: Template) -> None:
        # Lambda scales to many concurrent instances, so process-local session
        # memory would lose a follow-up routed to a different instance.
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Environment": Match.object_like(
                    {
                        "Variables": Match.object_like(
                            {"YOUTH_COMPASS_CONVERSATION__PROVIDER": "dynamodb"}
                        )
                    }
                )
            },
        )
