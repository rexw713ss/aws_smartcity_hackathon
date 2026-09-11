"""Deferred-service and always-on resource guard.

Feature: aws-stage1-foundation, Property 19.

Requirements 4.17, 4.18, 9.5, 9.6: no synthesized template may contain a Bedrock,
SageMaker, or Bedrock AgentCore resource, nor any of the five always-on types.
"""

import pytest

from tests.infra.conftest import synth_budget_stack

ENVS = ("dev", "demo", "hackathon")

DEFERRED_PREFIXES = ("AWS::Bedrock", "AWS::SageMaker", "AWS::BedrockAgentCore")
ALWAYS_ON_TYPES = {
    "AWS::SageMaker::Endpoint",
    "AWS::SageMaker::NotebookInstance",
    "AWS::EC2::NatGateway",
    "AWS::RDS::DBInstance",
    "AWS::EC2::EIP",
}


@pytest.mark.parametrize("env_name", ENVS)
def test_property_19_no_deferred_or_always_on_resources(env_name: str) -> None:
    template = synth_budget_stack(env_name).to_json()
    resources = template.get("Resources", {})
    offenders: list[str] = []
    for logical_id, resource in resources.items():
        rtype = resource.get("Type", "")
        if rtype.startswith(DEFERRED_PREFIXES) or rtype in ALWAYS_ON_TYPES:
            offenders.append(f"{env_name}:{logical_id}:{rtype}")
    assert not offenders, "forbidden resources synthesized:\n" + "\n".join(offenders)


def test_only_expected_resource_types_present() -> None:
    template = synth_budget_stack("dev").to_json()
    types = {r["Type"] for r in template.get("Resources", {}).values()}
    assert types == {"AWS::Budgets::Budget"}, types
