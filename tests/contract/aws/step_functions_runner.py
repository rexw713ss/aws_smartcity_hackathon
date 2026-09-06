"""Step Functions WorkflowRunner binding for the contract suite under moto."""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.step_functions_runner import StepFunctionsRunner
from tests.contract.registry import register_workflow_runner

_REGION = "ap-northeast-1"
_STATE_MACHINE_NAME = "contract-ingestion-workflow"

# Minimal single-Pass definition moto can handle.
_DEFINITION = json.dumps(
    {
        "StartAt": "PassState",
        "States": {
            "PassState": {"Type": "Pass", "End": True},
        },
    }
)


@register_workflow_runner("sfn-moto")
@contextmanager
def _sfn_runner() -> Iterator[StepFunctionsRunner]:
    with mock_aws():
        sfn = boto3.client("stepfunctions", region_name=_REGION)
        iam = boto3.client("iam", region_name=_REGION)
        role = iam.create_role(
            RoleName="sfn-execution-role",
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "states.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )
        sm = sfn.create_state_machine(
            name=_STATE_MACHINE_NAME,
            definition=_DEFINITION,
            roleArn=role["Role"]["Arn"],
        )
        yield StepFunctionsRunner(state_machine_arn=sm["stateMachineArn"], region=_REGION)
