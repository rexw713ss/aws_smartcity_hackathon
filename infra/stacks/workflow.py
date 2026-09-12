"""WorkflowStack: AWS orchestration for upload-driven ingestion.

Feature: aws-stage2-adapters (PR1 — AWS Orchestration Infrastructure).

Deploys the entry path the existing code already implements:

    S3 ObjectCreated (incoming/) -> EventBridge rule -> upload-event Lambda
    -> Step Functions Standard Workflow -> transform Lambda

- upload-event Lambda runs ``adapters.aws.upload_event_handler.handler`` and
  starts exactly one Step Functions execution per upload (idempotent on the
  job id, so retries do not double-start).
- transform Lambda runs ``adapters.aws.transform_lambda.handler``.
- Standard workflow (not Express) so the human-approval pause can wait.
- Least-privilege IAM per role.
- Environment variables the handlers and API require.
"""

from pathlib import Path
from typing import Any

import aws_cdk as cdk
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
_LAMBDA_ASSET = str(_REPO_ROOT / "build" / "transform_lambda")
_TRANSFORM_HANDLER = "adapters.aws.transform_lambda.handler"
_UPLOAD_EVENT_HANDLER = "adapters.aws.upload_event_handler.handler"
_LAMBDA_TIMEOUT = Duration.minutes(5)
_LAMBDA_MEMORY_MB = 1024


class WorkflowStack(TaggedStack):
    """Upload-driven ingestion orchestration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_config: EnvironmentConfig,
        incoming_bucket_name: str,
        standardized_bucket_name: str,
        curated_bucket_name: str,
        quarantined_bucket_name: str,
        metadata_table_name: str,
        glue_database_name: str,
        region: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, tags=env_config.tags, **kwargs)

        incoming = s3.Bucket.from_bucket_name(self, "IncomingRef", incoming_bucket_name)
        standardized = s3.Bucket.from_bucket_name(self, "StandardizedRef", standardized_bucket_name)
        curated = s3.Bucket.from_bucket_name(self, "CuratedRef", curated_bucket_name)
        quarantined = s3.Bucket.from_bucket_name(self, "QuarantinedRef", quarantined_bucket_name)
        metadata_table = dynamodb.Table.from_table_name(self, "MetadataRef", metadata_table_name)

        code = lambda_.Code.from_asset(_LAMBDA_ASSET)
        common_env = {
            "YOUTH_COMPASS_INCOMING_BUCKET": incoming_bucket_name,
            "YOUTH_COMPASS_REGION": region,
            "YOUTH_COMPASS_METADATA_TABLE": metadata_table_name,
            "YOUTH_COMPASS_CURATED_BUCKET": curated_bucket_name,
            "YOUTH_COMPASS_QUARANTINED_BUCKET": quarantined_bucket_name,
            "YOUTH_COMPASS_GLUE_DATABASE": glue_database_name,
        }

        # --- Transform Lambda (ARM64): profiling + mapping + transform ---
        self.transform_fn = lambda_.Function(
            self,
            "TransformFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=_TRANSFORM_HANDLER,
            code=code,
            timeout=_LAMBDA_TIMEOUT,
            memory_size=_LAMBDA_MEMORY_MB,
            environment=common_env,
        )
        incoming.grant_read(self.transform_fn)
        standardized.grant_read_write(self.transform_fn)
        curated.grant_read_write(self.transform_fn)
        quarantined.grant_read_write(self.transform_fn)
        metadata_table.grant_read_write_data(self.transform_fn)
        # Registering the curated table on publish. Scoped to this database's
        # tables: no access to other databases, and no delete.
        self.transform_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["glue:CreateTable", "glue:UpdateTable", "glue:GetTable"],
                resources=[
                    f"arn:aws:glue:{region}:{cdk.Aws.ACCOUNT_ID}:catalog",
                    f"arn:aws:glue:{region}:{cdk.Aws.ACCOUNT_ID}:database/{glue_database_name}",
                    f"arn:aws:glue:{region}:{cdk.Aws.ACCOUNT_ID}:table/{glue_database_name}/*",
                ],
            )
        )

        # --- Step Functions Standard Workflow ---
        # 1. Profile + map the uploaded file.
        analyze = tasks.LambdaInvoke(
            self,
            "ProfileAndMap",
            lambda_function=self.transform_fn,
            payload=sfn.TaskInput.from_object(
                {"action": "analyze", "source_uri": sfn.JsonPath.string_at("$.source_uri")}
            ),
            result_path="$.analysis",
        )

        # Terminal-ish steps.
        quarantine = tasks.LambdaInvoke(
            self,
            "Quarantine",
            lambda_function=self.transform_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "transform",
                    "approved": False,
                    "job_id": sfn.JsonPath.string_at("$.job_id"),
                    "source_uri": sfn.JsonPath.string_at("$.source_uri"),
                }
            ),
            result_path="$.quarantine",
        )
        publish = tasks.LambdaInvoke(
            self,
            "Publish",
            lambda_function=self.transform_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "transform",
                    "approved": True,
                    "job_id": sfn.JsonPath.string_at("$.job_id"),
                    "source_uri": sfn.JsonPath.string_at("$.source_uri"),
                }
            ),
            result_path="$.publish",
        )

        # 2. Real human-approval pause: waitForTaskToken. The Lambda persists the
        # token so the API can resume this exact execution later; the state
        # stays suspended (no per-hour charge) until send_task_success/failure.
        await_approval = tasks.LambdaInvoke(
            self,
            "AwaitApproval",
            lambda_function=self.transform_fn,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object(
                {
                    "action": "await_approval",
                    "job_id": sfn.JsonPath.string_at("$.job_id"),
                    "task_token": sfn.JsonPath.task_token,
                }
            ),
            result_path="$.approval",
        )
        # On approval the token returns success -> publish; on rejection the
        # token returns failure -> caught here -> quarantine.
        await_approval.add_catch(quarantine, errors=["Rejected"], result_path="$.rejection")
        await_approval.next(publish)

        # 3. Confidence gate: high confidence auto-publishes; else pause for review.
        gate = (
            sfn.Choice(self, "ConfidenceGate")
            .when(
                sfn.Condition.number_greater_than_equals(
                    "$.analysis.Payload.result.validation.overall_confidence", 0.95
                ),
                publish,
            )
            .otherwise(await_approval)
        )
        analyze.add_catch(quarantine, errors=["States.ALL"], result_path="$.error")

        self.state_machine = sfn.StateMachine(
            self,
            "IngestionWorkflow",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(analyze.next(gate)),
            timeout=Duration.hours(24),
        )
        self.transform_fn.grant_invoke(self.state_machine)

        # --- Upload-event Lambda: S3 event -> start Step Functions ---
        self.upload_event_fn = lambda_.Function(
            self,
            "UploadEventFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=_UPLOAD_EVENT_HANDLER,
            code=code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                **common_env,
                "YOUTH_COMPASS_STATE_MACHINE_ARN": self.state_machine.state_machine_arn,
            },
        )
        # Least privilege: HeadObject on incoming + StartExecution on the workflow.
        self.upload_event_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[incoming.arn_for_objects("incoming/*")],
            )
        )
        incoming.grant_read(self.upload_event_fn)  # includes HeadObject
        self.state_machine.grant_start_execution(self.upload_event_fn)

        # --- EventBridge rule: S3 ObjectCreated under incoming/ -> upload Lambda ---
        rule = events.Rule(
            self,
            "IncomingUploadRule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={
                    "bucket": {"name": [incoming_bucket_name]},
                    "object": {"key": [{"prefix": "incoming/"}]},
                },
            ),
        )
        rule.add_target(targets.LambdaFunction(self.upload_event_fn))

        # Env vars the API role needs are surfaced as stack outputs so the API
        # deployment can consume them.
        cdk.CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
        cdk.CfnOutput(self, "IncomingBucket", value=incoming_bucket_name)
