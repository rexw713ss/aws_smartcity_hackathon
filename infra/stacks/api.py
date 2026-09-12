"""ApiStack: the public HTTP surface — API Lambda, HTTP API, and static site.

Feature: API deployment (lean MVP).

    Browser ──HTTPS──> CloudFront ──> S3 (static frontend, private via OAC)
       │
       └──/api/v1 XHR──> API Gateway HTTP API ──> API Lambda (ARM64, Mangum)
                                                    ├── S3 presigned uploads
                                                    ├── Step Functions (resume)
                                                    ├── DynamoDB (job state)
                                                    └── Bedrock (copilot)

Design notes:

- Lambda rather than Fargate or App Runner: this project holds a hard line
  against always-on compute (see docs/aws-workstream-status.md section 7), and a
  request-billed function keeps the idle cost at zero.
- The frontend is served by CloudFront from a private bucket. The API is called
  directly over its own HTTPS endpoint rather than proxied through CloudFront,
  which keeps this stack small; the tradeoff is that CORS must be configured,
  which it is, on both the API and the bucket.
- ``states:SendTaskSuccess``/``SendTaskFailure`` is granted here. Without it a
  deployed API cannot resume a paused approval, which was an outstanding gap.
"""

import os
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    Duration,
)
from aws_cdk import (
    aws_apigatewayv2 as apigw,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as integrations,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
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
from constructs import Construct

from infra.environments import EnvironmentConfig
from infra.errors import InfraConfigError
from infra.stacks.base import TaggedStack

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_ASSET = str(_REPO_ROOT / "build" / "api_lambda")
_API_HANDLER = "apps.api.lambda_handler.handler"

_WRITE_SECRET_CONTEXT_KEY = "writeSecret"
_WRITE_SECRET_ENV_VAR = "YOUTH_COMPASS_WRITE_SECRET"
_MIN_WRITE_SECRET_LENGTH = 16

_MODEL_ID_CONTEXT_KEY = "modelId"
_MODEL_ID_ENV_VAR = "YOUTH_COMPASS_MODEL_ID"
# Verified invokable on the hackathon account; Claude is not available there.
_DEFAULT_MODEL_ID = "amazon.nova-lite-v1:0"


def resolve_write_secret(context_value: str | None) -> str:
    """Context key preferred, then the environment variable; never committed.

    Refuses to synthesize without one. A deployed API with no write secret would
    let any caller approve an ingestion job and publish data, so this is a hard
    failure rather than a defaulted value.
    """
    value = context_value or os.environ.get(_WRITE_SECRET_ENV_VAR)
    if not value or len(value) < _MIN_WRITE_SECRET_LENGTH:
        raise InfraConfigError(
            "API write secret is missing or too short (minimum "
            f"{_MIN_WRITE_SECRET_LENGTH} characters); set the CDK context key "
            f"-c {_WRITE_SECRET_CONTEXT_KEY}=... or the environment variable "
            f"{_WRITE_SECRET_ENV_VAR}. Generate one with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    return value


def resolve_model_id(context_value: str | None) -> str:
    """Context key, then environment variable, then the verified default."""
    return context_value or os.environ.get(_MODEL_ID_ENV_VAR) or _DEFAULT_MODEL_ID


# Cold start dominates this function's latency; the analytics endpoints open
# DuckDB over a bundled Parquet file, so give it room to breathe.
_API_TIMEOUT = Duration.seconds(30)
_API_MEMORY_MB = 1024


class ApiStack(TaggedStack):
    """Public API and static frontend hosting."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_config: EnvironmentConfig,
        incoming_bucket_name: str,
        curated_bucket_name: str,
        metadata_table_name: str,
        glue_database_name: str,
        state_machine_arn: str,
        region: str,
        model_id: str,
        write_secret: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, tags=env_config.tags, **kwargs)

        prefix = env_config.stack_prefix.lower().replace("-", "")

        # --- Static frontend bucket (private; CloudFront reads it via OAC) ---
        self.site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=f"{prefix}-site-{cdk.Aws.ACCOUNT_ID}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # The account is reclaimed after the event; leaving no orphaned
            # bucket behind is deliberate.
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "SiteDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            # Single-page apps route client-side: unknown paths must still serve
            # index.html rather than CloudFront's XML error document.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=status,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                )
                for status in (403, 404)
            ],
        )

        site_origin = f"https://{self.distribution.distribution_domain_name}"

        # --- API Lambda ---
        incoming = s3.Bucket.from_bucket_name(self, "IncomingRef", incoming_bucket_name)
        curated = s3.Bucket.from_bucket_name(self, "CuratedRef", curated_bucket_name)
        metadata_table = dynamodb.Table.from_table_name(self, "MetadataRef", metadata_table_name)

        self.api_fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=_API_HANDLER,
            code=lambda_.Code.from_asset(_API_ASSET),
            timeout=_API_TIMEOUT,
            memory_size=_API_MEMORY_MB,
            environment={
                "YOUTH_COMPASS_ENVIRONMENT": "aws",
                "YOUTH_COMPASS_REGION": region,
                # /var/task is read-only; the handler seeds this writable copy
                # from the baked data on cold start.
                "YOUTH_COMPASS_DATA_ROOT": "/tmp/youth-compass-data",
                "YOUTH_COMPASS_BAKED_DATA_ROOT": "/var/task/data",
                "YOUTH_COMPASS_INCOMING_BUCKET": incoming_bucket_name,
                "YOUTH_COMPASS_CURATED_BUCKET": curated_bucket_name,
                "YOUTH_COMPASS_METADATA_TABLE": metadata_table_name,
                "YOUTH_COMPASS_GLUE_DATABASE": glue_database_name,
                "YOUTH_COMPASS_STATE_MACHINE_ARN": state_machine_arn,
                # Bedrock: ap-northeast-1 is SCP-denied on the hackathon
                # account, so the model region follows this stack's region.
                "YOUTH_COMPASS_MODEL__PROVIDER": "bedrock",
                "YOUTH_COMPASS_MODEL__MODEL_ID": model_id,
                "YOUTH_COMPASS_MODEL__REGION": region,
                "YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS": site_origin,
                "YOUTH_COMPASS_API__WRITE_SECRET": write_secret,
            },
        )

        # Presigned uploads sign a PUT/POST into incoming; verify_upload reads
        # object metadata back.
        incoming.grant_read_write(self.api_fn)
        curated.grant_read(self.api_fn)
        metadata_table.grant_read_write_data(self.api_fn)

        # Resuming a paused approval. This is the permission a deployed API was
        # previously missing entirely.
        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "states:StartExecution",
                    "states:DescribeExecution",
                    "states:SendTaskSuccess",
                    "states:SendTaskFailure",
                ],
                resources=[
                    state_machine_arn,
                    f"{state_machine_arn.replace(':stateMachine:', ':execution:')}:*",
                ],
            )
        )

        # The copilot's decomposer calls Bedrock Converse. Scoped to the
        # foundation model actually configured, not "*".
        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{region}::foundation-model/{model_id}",
                    f"arn:aws:bedrock:{region}:{cdk.Aws.ACCOUNT_ID}:inference-profile/{model_id}",
                ],
            )
        )

        # --- HTTP API ---
        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"{env_config.stack_prefix}-api",
            # The app also sets CORS headers. Configuring them here too means a
            # preflight is answered at the edge without a Lambda invocation.
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=[site_origin],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Content-Type", "X-Youth-Compass-Token"],
                max_age=Duration.minutes(10),
            ),
            default_integration=integrations.HttpLambdaIntegration(
                "ApiIntegration",
                handler=self.api_fn,
            ),
        )

        cdk.CfnOutput(self, "ApiBaseUrl", value=self.http_api.api_endpoint)
        cdk.CfnOutput(self, "SiteUrl", value=site_origin)
        cdk.CfnOutput(self, "SiteBucketName", value=self.site_bucket.bucket_name)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
