"""Durable workflow state survives runner restarts.

Feature: aws-stage2-adapters (PR2). Proves the approval state and callback token
persist in DynamoDB, so a fresh runner instance (simulating an API/Lambda
restart) can still resume a paused job — the exact gap PR2 called out.
"""

from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from adapters.aws.step_functions_runner import StepFunctionsRunner
from adapters.aws.workflow_token_store import WorkflowTokenStore
from youth_compass.domain.errors import WorkflowStateError
from youth_compass.ingestion import profile_csv
from youth_compass.mapping import analyze_mapping
from youth_compass.ports.workflow_runner import ApprovalDecision, JobStatus

REGION = "us-east-1"
TABLE = "workflow-state"


def _decision(approved: bool) -> ApprovalDecision:
    return ApprovalDecision(approved=approved, decided_by="reviewer", decided_at=datetime.now(UTC))


@pytest.fixture
def _table() -> None:
    with mock_aws():
        boto3.resource("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "dataset_id", "KeyType": "HASH"},
                {"AttributeName": "version", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "dataset_id", "AttributeType": "S"},
                {"AttributeName": "version", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


class TestDurableWorkflowState:
    def test_status_survives_a_runner_restart(self, _table: None) -> None:
        store = WorkflowTokenStore(TABLE, REGION)
        store.put_status("job-1", JobStatus.AWAITING_APPROVAL)
        store.put_token("job-1", "task-token-abc")

        # Simulate an API/Lambda restart: a brand-new store instance.
        fresh = WorkflowTokenStore(TABLE, REGION)
        assert fresh.get_status("job-1") is JobStatus.AWAITING_APPROVAL
        assert fresh.get_token("job-1") == "task-token-abc"

    def test_resume_unknown_job_raises(self, _table: None) -> None:
        store = WorkflowTokenStore(TABLE, REGION)
        runner = StepFunctionsRunner(
            "arn:aws:states:us-east-1:000000000000:stateMachine:x",
            REGION,
            token_store=store,
        )
        with pytest.raises(WorkflowStateError):
            runner.resume_after_approval("no-such-job", _decision(True))

    def test_missing_token_raises(self, _table: None) -> None:
        store = WorkflowTokenStore(TABLE, REGION)
        store.put_status("job-2", JobStatus.AWAITING_APPROVAL)  # status but no token
        runner = StepFunctionsRunner(
            "arn:aws:states:us-east-1:000000000000:stateMachine:x",
            REGION,
            token_store=store,
        )
        with pytest.raises(WorkflowStateError, match="no pending approval token"):
            runner.resume_after_approval("job-2", _decision(True))

    def test_clear_token_removes_it(self, _table: None) -> None:
        store = WorkflowTokenStore(TABLE, REGION)
        store.put_token("job-3", "t")
        store.clear_token("job-3")
        assert store.get_token("job-3") is None

    def test_mapping_review_survives_a_runner_restart(self, _table: None) -> None:
        analysis = analyze_mapping(profile_csv(Path("data/samples/population_demo.csv")))
        WorkflowTokenStore(TABLE, REGION).put_mapping_analysis("job-review", analysis)

        fresh = StepFunctionsRunner(
            "arn:aws:states:us-east-1:000000000000:stateMachine:x",
            REGION,
            token_store=WorkflowTokenStore(TABLE, REGION),
        )

        assert fresh.get_mapping_analysis("job-review") == analysis
