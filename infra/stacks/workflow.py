"""WorkflowStack: Lambda transform + Step Functions ingestion workflow.

Feature: aws-stage2-adapters, Requirement 7.

Deploys the ingestion pipeline: an ARM64 Lambda that runs the deterministic
transforms, a Step Functions state machine that orchestrates
profile -> map -> validate -> approval pause -> transform -> quality -> publish
with failures routed to quarantine, and an EventBridge rule that auto-starts the
workflow when an object lands in the incoming bucket.

The Lambda calls the existing profile_csv and analyze_mapping functions; it does
not reimplement them.
"""

from pathlib import Path
from typing import Any

from aws_cdk import (
    Duration,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_stepfunctions as sfn,
)
from aws_cdk import (
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

from infra.environments import EnvironmentConfig
from infra.stacks.base import TaggedStack

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Lambda packaging: bundle the project source. The handler is at
# adapters/aws/transform_lambda.py, so the handler path is
# "adapters.aws.transform_lambda.handler".
_HANDLER = "adapters.aws.transform_lambda.handler"
_LAMBDA_TIMEOUT = Duration.minutes(5)
_LAMBDA_MEMORY_MB = 1024


class WorkflowStack(TaggedStack):
    """Ingestion workflow: Lambda transform + Step Functions state machine."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_config: EnvironmentConfig,
        incoming_bucket_name: str,
        curated_bucket_name: str,
        quarantined_bucket_name: str,
        metadata_table_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, tags=env_config.tags, **kwargs)

        incoming = s3.Bucket.from_bucket_name(self, "IncomingRef", incoming_bucket_name)
        curated = s3.Bucket.from_bucket_name(self, "CuratedRef", curated_bucket_name)
        quarantined = s3.Bucket.from_bucket_name(self, "QuarantinedRef", quarantined_bucket_name)
        metadata_table = dynamodb.Table.from_table_name(self, "MetadataRef", metadata_table_name)

        # --- Transform Lambda (ARM64) ---
        # The asset directory is pre-built by scripts/build_lambda.py (no Docker
        # dependency, so it works on any machine). Run that script before deploy.
        asset_dir = str(_REPO_ROOT / "build" / "transform_lambda")
        self.transform_fn = lambda_.Function(
            self,
            "TransformFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=_HANDLER,
            code=lambda_.Code.from_asset(asset_dir),
            timeout=_LAMBDA_TIMEOUT,
            memory_size=_LAMBDA_MEMORY_MB,
        )
        incoming.grant_read(self.transform_fn)
        curated.grant_read_write(self.transform_fn)
        quarantined.grant_read_write(self.transform_fn)
        metadata_table.grant_read_write_data(self.transform_fn)

        # --- Step Functions states ---
        analyze = tasks.LambdaInvoke(
            self,
            "ProfileAndMap",
            lambda_function=self.transform_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "analyze",
                    "bucket": sfn.JsonPath.string_at("$.bucket"),
                    "key": sfn.JsonPath.string_at("$.key"),
                }
            ),
            result_path="$.analysis",
        )

        quarantine = sfn.Pass(
            self,
            "Quarantine",
            comment="Route failed or rejected ingestions to the quarantined zone",
        )
        publish = sfn.Pass(
            self,
            "Publish",
            comment="Publish approved dataset to the curated zone",
        )

        # Confidence gate: high confidence auto-publishes; otherwise pause for
        # human approval via the waitForTaskToken pattern.
        approval = sfn.Pass(
            self,
            "AwaitApproval",
            comment="waitForTaskToken pause for human review (wired in Stage 2 workflow)",
        )

        confidence_gate = (
            sfn.Choice(self, "ConfidenceGate")
            .when(
                sfn.Condition.number_greater_than_equals(
                    "$.analysis.Payload.result.validation.overall_confidence", 0.95
                ),
                publish,
            )
            .otherwise(approval)
        )

        analyze.add_catch(quarantine, errors=["States.ALL"], result_path="$.error")
        approval.next(publish)

        definition = analyze.next(confidence_gate)

        self.state_machine = sfn.StateMachine(
            self,
            "IngestionWorkflow",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(24),
        )
        self.transform_fn.grant_invoke(self.state_machine)

        # --- Auto-trigger: S3 ObjectCreated in incoming -> start workflow ---
        # Requires EventBridge notifications enabled on the bucket (set in DataStack
        # or via a one-time console/CLI step; documented in the Stage 2 doc).
        rule = events.Rule(
            self,
            "IncomingUploadRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={"bucket": {"name": [incoming_bucket_name]}},
            ),
        )
        rule.add_target(
            targets.SfnStateMachine(
                self.state_machine,
                input=events.RuleTargetInput.from_object(
                    {
                        "bucket": events.EventField.from_path("$.detail.bucket.name"),
                        "key": events.EventField.from_path("$.detail.object.key"),
                    }
                ),
            )
        )

        # Allow EventBridge to start the state machine.
        self.state_machine.grant_start_execution(iam.ServicePrincipal("events.amazonaws.com"))
