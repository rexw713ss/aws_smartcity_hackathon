"""DataStack assertion tests.

Feature: aws-stage2-adapters, Requirement 1.
Properties 8/9 (IAM role separation), 10 (six buckets), 11 (Glue+DynamoDB),
12 (no deferred services), 13 (free synthesis), 14 (tags).
"""

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.environments import resolve_environment
from infra.stacks.data import DataStack
from tests.infra.constants import PLACEHOLDER_ACCOUNT, PLACEHOLDER_REGION


def _synth(env_name: str = "dev") -> Template:
    app = cdk.App()
    config = resolve_environment(env_name)
    stack = DataStack(
        app,
        f"{config.stack_prefix}-Data",
        env_config=config,
        env=cdk.Environment(account=PLACEHOLDER_ACCOUNT, region=PLACEHOLDER_REGION),
    )
    return Template.from_stack(stack)


class TestBuckets:
    def test_exactly_six_s3_buckets(self) -> None:
        template = _synth()
        template.resource_count_is("AWS::S3::Bucket", 6)

    def test_all_buckets_versioned_and_public_access_blocked(self) -> None:
        template = _synth()
        resources = template.find_resources("AWS::S3::Bucket")
        for _logical_id, resource in resources.items():
            props = resource["Properties"]
            assert props.get("VersioningConfiguration", {}).get("Status") == "Enabled"
            pab = props.get("PublicAccessBlockConfiguration", {})
            assert pab.get("BlockPublicAcls") is True
            assert pab.get("BlockPublicPolicy") is True

    def test_incoming_has_lifecycle_rule(self) -> None:
        template = _synth()
        resources = template.find_resources("AWS::S3::Bucket")
        incoming = [
            r
            for r in resources.values()
            if "incoming" in str(r.get("Properties", {}).get("BucketName", ""))
        ]
        assert incoming
        rules = incoming[0]["Properties"].get("LifecycleConfiguration", {}).get("Rules", [])
        assert any(r.get("ExpirationInDays") == 30 for r in rules)


class TestCatalogResources:
    def test_exactly_one_glue_database(self) -> None:
        template = _synth()
        template.resource_count_is("AWS::Glue::Database", 1)

    def test_exactly_one_dynamodb_table_on_demand(self) -> None:
        template = _synth()
        template.resource_count_is("AWS::DynamoDB::Table", 1)
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"BillingMode": "PAY_PER_REQUEST"},
        )


class TestIAMRoles:
    def test_copilot_has_explicit_deny_on_curated_write(self) -> None:
        template = _synth()
        policies = template.find_resources("AWS::IAM::Policy")
        found_deny = False
        for _id, policy in policies.items():
            doc = policy.get("Properties", {}).get("PolicyDocument", {})
            for statement in doc.get("Statement", []):
                if statement.get("Effect") == "Deny":
                    actions = statement.get("Action", [])
                    if isinstance(actions, str):
                        actions = [actions]
                    if "s3:PutObject" in actions and "s3:DeleteObject" in actions:
                        found_deny = True
        assert found_deny, "no explicit deny for PutObject+DeleteObject found"

    def test_write_role_and_copilot_role_are_distinct(self) -> None:
        template = _synth()
        roles = template.find_resources("AWS::IAM::Role")
        descriptions = [r.get("Properties", {}).get("Description", "") for r in roles.values()]
        assert "write" in " ".join(descriptions).lower()
        assert (
            "copilot" in " ".join(descriptions).lower()
            or "read-only" in " ".join(descriptions).lower()
        )


class TestDeferredServices:
    def test_no_bedrock_sagemaker_or_agentcore_resources(self) -> None:
        for env_name in ("dev", "demo", "hackathon"):
            template = _synth(env_name).to_json()
            for _logical_id, resource in template.get("Resources", {}).items():
                rtype = resource.get("Type", "")
                assert not rtype.startswith("AWS::Bedrock"), rtype
                assert not rtype.startswith("AWS::SageMaker"), rtype
                assert not rtype.startswith("AWS::BedrockAgentCore"), rtype

    def test_no_always_on_resources(self) -> None:
        always_on = {
            "AWS::SageMaker::Endpoint",
            "AWS::SageMaker::NotebookInstance",
            "AWS::EC2::NatGateway",
            "AWS::RDS::DBInstance",
            "AWS::EC2::EIP",
        }
        for env_name in ("dev", "demo", "hackathon"):
            template = _synth(env_name).to_json()
            for _logical_id, resource in template.get("Resources", {}).items():
                assert resource.get("Type", "") not in always_on


class TestTags:
    def test_all_stacks_carry_four_mandatory_tags(self) -> None:
        for env_name in ("dev", "demo", "hackathon"):
            config = resolve_environment(env_name)
            for tag in ("Project", "Environment", "Owner", "CostCenter"):
                assert config.tags[tag].strip()


class TestSynthesis:
    def test_synthesis_produces_a_template_per_env(self) -> None:
        for env_name in ("dev", "demo", "hackathon"):
            template = _synth(env_name)
            assert template.to_json().get("Resources")
