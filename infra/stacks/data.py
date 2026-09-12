"""DataStack: S3 data-lake buckets, Glue database, DynamoDB metadata table, and IAM roles.

Feature: aws-stage2-adapters, Requirement 1.

Six S3 zones (incoming, quarantined, standardized, curated, forecasts, metadata),
each versioned with public access blocked. Incoming expires after 30 days,
quarantined after 90 days. One Glue database, one on-demand DynamoDB table, and
two IAM roles: a Write_Role for the ingestion workflow and a Copilot_Role that is
explicitly denied writes on curated paths.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
)
from aws_cdk import (
    aws_athena as athena,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_glue as glue,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

from infra.environments import EnvironmentConfig
from infra.stacks.base import TaggedStack

# Lifecycle rules: incoming 30 days, quarantined 90 days.
_INCOMING_EXPIRY_DAYS = 30
_QUARANTINED_EXPIRY_DAYS = 90

_ZONES = ("incoming", "quarantined", "standardized", "curated", "forecasts", "metadata")

# Athena is billed per byte scanned. The curated datasets are a few MB, so this
# cap is a guardrail against a runaway query, not a working limit — a single
# scan should never approach it. Enforced at the workgroup so no per-query
# override can raise it.
_ATHENA_SCAN_CAP_BYTES = 1024 * 1024 * 1024  # 1 GiB
_ATHENA_RESULTS_PREFIX = "athena-results/"


class DataStack(TaggedStack):
    """Data-lake infrastructure: buckets, catalog, metadata table, IAM roles."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_config: EnvironmentConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, tags=env_config.tags, **kwargs)

        prefix = env_config.stack_prefix.lower().replace("-", "")

        # Browser-based multipart POST uploads need CORS on the incoming bucket.
        _incoming_cors = [
            s3.CorsRule(
                allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.PUT],
                allowed_origins=["*"],  # tighten to the dashboard origin in production
                allowed_headers=["*"],
                exposed_headers=["ETag"],
                max_age=3000,
            )
        ]

        # --- S3 buckets per data zone ---
        self.buckets: dict[str, s3.Bucket] = {}
        for zone in _ZONES:
            lifecycle_rules: list[s3.LifecycleRule] = []
            if zone == "incoming":
                lifecycle_rules.append(
                    s3.LifecycleRule(expiration=Duration.days(_INCOMING_EXPIRY_DAYS))
                )
            elif zone == "quarantined":
                lifecycle_rules.append(
                    s3.LifecycleRule(expiration=Duration.days(_QUARANTINED_EXPIRY_DAYS))
                )
            bucket = s3.Bucket(
                self,
                f"{zone}-bucket",
                bucket_name=f"{prefix}-{zone}-{cdk.Aws.ACCOUNT_ID}",
                versioned=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_objects=True,
                lifecycle_rules=lifecycle_rules if lifecycle_rules else None,
                # EventBridge notifications on incoming drive the ingestion trigger.
                event_bridge_enabled=(zone == "incoming"),
                cors=_incoming_cors if zone == "incoming" else None,
            )
            self.buckets[zone] = bucket

        # --- Glue database ---
        self.glue_database_name = f"youth_compass_{env_config.name}"
        self.glue_db = glue.CfnDatabase(
            self,
            "GlueDatabase",
            catalog_id=cdk.Aws.ACCOUNT_ID,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=self.glue_database_name,
            ),
        )

        # --- Athena workgroup for read-only analytics ---
        # Results land under a prefix of the metadata bucket. enforce_work_group
        # _configuration=True means a caller cannot override the output location
        # or the scan cap, so the guardrail cannot be bypassed per query.
        self.athena_workgroup_name = f"{prefix}-analytics"
        self.athena_results_uri = (
            f"s3://{self.buckets['metadata'].bucket_name}/{_ATHENA_RESULTS_PREFIX}"
        )
        self.athena_workgroup = athena.CfnWorkGroup(
            self,
            "AnalyticsWorkGroup",
            name=self.athena_workgroup_name,
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                bytes_scanned_cutoff_per_query=_ATHENA_SCAN_CAP_BYTES,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=self.athena_results_uri,
                ),
            ),
        )

        # --- DynamoDB metadata table (on-demand, no provisioned capacity) ---
        self.metadata_table = dynamodb.Table(
            self,
            "MetadataTable",
            table_name=f"{prefix}-metadata",
            partition_key=dynamodb.Attribute(name="dataset_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="version", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- IAM roles ---
        curated_bucket = self.buckets["curated"]

        # Write_Role: used by the ingestion workflow service.
        self.write_role = iam.Role(
            self,
            "WriteRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Ingestion workflow write access to the data lake",
        )
        for zone in ("standardized", "curated", "forecasts", "metadata"):
            self.buckets[zone].grant_read_write(self.write_role)
        self.metadata_table.grant_read_write_data(self.write_role)

        # Copilot_Role: read-only for the policy copilot. Explicitly denied
        # writes on curated paths so the copilot physically cannot mutate
        # published data.
        self.copilot_role = iam.Role(
            self,
            "CopilotRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Read-only copilot access to curated data",
        )
        curated_bucket.grant_read(self.copilot_role)
        self.metadata_table.grant_read_data(self.copilot_role)

        # Explicit deny: belt-and-suspenders so a policy misconfiguration
        # cannot accidentally grant the copilot write access.
        self.copilot_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=["s3:PutObject", "s3:DeleteObject"],
                resources=[curated_bucket.arn_for_objects("*")],
            )
        )

        # Names the API deployment consumes to wire its Athena adapter.
        cdk.CfnOutput(self, "GlueDatabaseName", value=self.glue_database_name)
        cdk.CfnOutput(self, "AthenaWorkGroupName", value=self.athena_workgroup_name)
        cdk.CfnOutput(self, "AthenaResultsUri", value=self.athena_results_uri)
        cdk.CfnOutput(self, "MetadataBucketName", value=self.buckets["metadata"].bucket_name)
        cdk.CfnOutput(self, "CuratedBucketName", value=curated_bucket.bucket_name)
