"""ApiStack: the public HTTP surface — API Lambda, HTTP API, and static site.

Feature: API deployment (lean MVP).

    Browser ──HTTPS──> CloudFront ──> S3 (static frontend, private via OAC)
       │
       └──/api/v1 XHR──> Lambda Function URL (response stream)
                         ──> API Lambda (ARM64, Lambda Web Adapter)
                                                    ├── S3 presigned uploads
                                                    ├── Step Functions (resume)
                                                    ├── DynamoDB (job state)
                                                    └── Bedrock (copilot)

Design notes:

- Lambda rather than Fargate or App Runner: this project holds a hard line
  against always-on compute (see docs/aws-workstream-status.md section 7), and a
  request-billed function keeps the idle cost at zero.
- The frontend is served by CloudFront from a private bucket. The Function URL is called
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
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

from infra.environments import EnvironmentConfig
from infra.stacks.base import TaggedStack

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_ASSET = str(_REPO_ROOT / "build" / "api_lambda")
_API_HANDLER = "run.sh"
_LWA_LAYER_ACCOUNT = "753240598075"
_LWA_LAYER_VERSION = 28

_MODEL_ID_ENV_VAR = "YOUTH_COMPASS_MODEL_ID"
# Verified with both Converse and JSON-schema structured output on the
# hackathon account. Newer Anthropic models must use a cross-region inference
# profile rather than the plain foundation-model id.
_DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

_INFERENCE_PROFILE_PREFIXES = ("us.", "apac.", "eu.", "global.")


def resolve_model_id(context_value: str | None) -> str:
    """Context key, then environment variable, then the verified default."""
    return context_value or os.environ.get(_MODEL_ID_ENV_VAR) or _DEFAULT_MODEL_ID


def _bedrock_resources(model_id: str, region: str) -> list[str]:
    """Return least-privilege ARNs for a foundation model or inference profile.

    Cross-region profiles require permission on both the profile itself and its
    underlying foundation model. The latter may be invoked in another region,
    so only the region segment is wildcarded; the provider/model remains exact.
    """

    if model_id.startswith(_INFERENCE_PROFILE_PREFIXES):
        foundation_model_id = model_id.split(".", 1)[1]
        return [
            (
                f"arn:{cdk.Aws.PARTITION}:bedrock:{region}:"
                f"{cdk.Aws.ACCOUNT_ID}:inference-profile/{model_id}"
            ),
            (f"arn:{cdk.Aws.PARTITION}:bedrock:*::foundation-model/{foundation_model_id}"),
        ]
    return [f"arn:{cdk.Aws.PARTITION}:bedrock:{region}::foundation-model/{model_id}"]


# Cold start dominates this function's latency; the analytics endpoints open
# DuckDB over a bundled Parquet file, so give it room to breathe.
_API_TIMEOUT = Duration.seconds(90)
_API_MEMORY_MB = 1024
#: The copilot route is public and each call can invoke Bedrock twice, so an
#: unbounded caller would spend real money before the budget alarm ever fires.
#:
#: Reserved concurrency is the only cap this surface has. Streaming answers
#: require a Lambda Function URL — an API Gateway HTTP API buffers the response
#: and collapses the live Bedrock stream back into one payload — and a Function
#: URL has no stage, so there is no edge rate limit to configure. A caller can
#: therefore still issue requests as fast as it likes; what it cannot do is have
#: more than this many handlers, and so more than this many Bedrock calls, in
#: flight at once. Anything stricter needs authentication or CloudFront in front
#: of the URL, neither of which this stack has yet.
_API_RESERVED_CONCURRENCY = 20


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
        metadata_bucket_name: str,
        metadata_table_name: str,
        glue_database_name: str,
        athena_workgroup_name: str,
        state_machine_arn: str,
        region: str,
        model_id: str,
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

        # --- Write guard secret ---
        # Generated by Secrets Manager rather than passed in: a value supplied at
        # synth time would be written into the CloudFormation template and into
        # the function's environment, both readable by anyone with console
        # access. The function reads it at runtime instead, and an operator who
        # needs to call a write endpoint fetches it with
        # ``aws secretsmanager get-secret-value --secret-id <WriteSecretName>``.
        self.write_secret = secretsmanager.Secret(
            self,
            "WriteSecret",
            secret_name=f"{env_config.stack_prefix}-api-write-secret",
            description="Shared secret required by the Youth Compass API write endpoints.",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=48,
                # The value travels in an HTTP header, so keep it to characters
                # that need no quoting in a shell or a curl invocation.
                exclude_punctuation=True,
                exclude_characters=" %+~`#$&*()|[]{}:;<>?!'/\\\"@",
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # --- API Lambda ---
        incoming = s3.Bucket.from_bucket_name(self, "IncomingRef", incoming_bucket_name)
        curated = s3.Bucket.from_bucket_name(self, "CuratedRef", curated_bucket_name)
        metadata = s3.Bucket.from_bucket_name(self, "MetadataBucketRef", metadata_bucket_name)
        metadata_table = dynamodb.Table.from_table_name(self, "MetadataRef", metadata_table_name)
        # The analytics workgroup is owned by the DataStack (it owns the data
        # lake and its query infra) and passed in by name, so there is exactly
        # one workgroup, exposed as a stack output.

        self.api_fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=_API_HANDLER,
            code=lambda_.Code.from_asset(_API_ASSET),
            timeout=_API_TIMEOUT,
            memory_size=_API_MEMORY_MB,
            reserved_concurrent_executions=_API_RESERVED_CONCURRENCY,
            environment={
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap",
                "AWS_LWA_INVOKE_MODE": "response_stream",
                "AWS_LWA_PORT": "8000",
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
                # Read analytics through Glue + Athena over the curated zone.
                "YOUTH_COMPASS_STORAGE__PROVIDER": "s3",
                "YOUTH_COMPASS_STORAGE__BUCKET": curated_bucket_name,
                "YOUTH_COMPASS_CATALOG__PROVIDER": "glue",
                "YOUTH_COMPASS_CATALOG__DATABASE": glue_database_name,
                "YOUTH_COMPASS_CATALOG__TABLE_NAME": metadata_table_name,
                "YOUTH_COMPASS_QUERY__PROVIDER": "athena",
                "YOUTH_COMPASS_QUERY__WORKGROUP": athena_workgroup_name,
                "YOUTH_COMPASS_QUERY__OUTPUT_BUCKET": metadata_bucket_name,
                "YOUTH_COMPASS_FORECAST__PROVIDER": "local",
                # Bedrock: ap-northeast-1 is SCP-denied on the hackathon
                # account, so the model region follows this stack's region.
                "YOUTH_COMPASS_MODEL__PROVIDER": "bedrock",
                "YOUTH_COMPASS_MODEL__MODEL_ID": model_id,
                "YOUTH_COMPASS_MODEL__REGION": region,
                "YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS": site_origin,
                "YOUTH_COMPASS_API__WRITE_SECRET_ARN": self.write_secret.secret_arn,
                # Lambda scales to many concurrent instances, so follow-up
                # session scope must live in the shared table rather than in one
                # process. Records expire through the table's TTL attribute.
                "YOUTH_COMPASS_CONVERSATION__PROVIDER": "dynamodb",
                "YOUTH_COMPASS_CONVERSATION__TABLE_NAME": metadata_table_name,
            },
            layers=[
                lambda_.LayerVersion.from_layer_version_arn(
                    self,
                    "LambdaWebAdapter",
                    (
                        f"arn:{cdk.Aws.PARTITION}:lambda:{region}:"
                        f"{_LWA_LAYER_ACCOUNT}:layer:LambdaAdapterLayerArm64:"
                        f"{_LWA_LAYER_VERSION}"
                    ),
                )
            ],
        )

        self.write_secret.grant_read(self.api_fn)

        # Presigned uploads sign a PUT/POST into incoming; verify_upload reads
        # object metadata back.
        incoming.grant_read_write(self.api_fn)
        curated.grant_read(self.api_fn)
        metadata_table.grant_read_write_data(self.api_fn)

        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetBucketLocation", "s3:ListBucket"],
                resources=[metadata.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["athena-results/*"]}},
            )
        )
        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"],
                resources=[metadata.arn_for_objects("athena-results/*")],
            )
        )

        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StartQueryExecution",
                    "athena:StopQueryExecution",
                ],
                resources=[
                    f"arn:{cdk.Aws.PARTITION}:athena:{region}:"
                    f"{cdk.Aws.ACCOUNT_ID}:workgroup/{athena_workgroup_name}"
                ],
            )
        )
        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:GetPartitions",
                    "glue:GetTable",
                    "glue:GetTables",
                ],
                resources=[
                    f"arn:{cdk.Aws.PARTITION}:glue:{region}:{cdk.Aws.ACCOUNT_ID}:catalog",
                    (
                        f"arn:{cdk.Aws.PARTITION}:glue:{region}:"
                        f"{cdk.Aws.ACCOUNT_ID}:database/{glue_database_name}"
                    ),
                    (
                        f"arn:{cdk.Aws.PARTITION}:glue:{region}:"
                        f"{cdk.Aws.ACCOUNT_ID}:table/{glue_database_name}/*"
                    ),
                ],
            )
        )
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

        # The answer composer calls Bedrock Converse. Cross-region inference
        # profiles additionally need the exact underlying foundation model in
        # every region the profile may route through.
        self.api_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=_bedrock_resources(model_id, region),
            )
        )

        # Function URLs preserve ASGI response chunks through Lambda Web
        # Adapter. API Gateway HTTP APIs buffer them and would turn the live
        # Bedrock response back into a single payload after deployment.
        self.function_url = self.api_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            invoke_mode=lambda_.InvokeMode.RESPONSE_STREAM,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=[site_origin],
                allowed_methods=[lambda_.HttpMethod.GET, lambda_.HttpMethod.POST],
                allowed_headers=["Content-Type", "X-Youth-Compass-Token"],
                max_age=Duration.minutes(10),
            ),
        )

        cdk.CfnOutput(self, "ApiBaseUrl", value=self.function_url.url)
        cdk.CfnOutput(self, "WriteSecretName", value=self.write_secret.secret_name)
        cdk.CfnOutput(self, "SiteUrl", value=site_origin)
        cdk.CfnOutput(self, "SiteBucketName", value=self.site_bucket.bucket_name)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
