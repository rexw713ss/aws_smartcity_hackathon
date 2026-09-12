"""CDK application entry point.

Synthesized but never deployed in Stage 1. Resolves the context environment and
region, then constructs the budget stack. Any InfraConfigError propagates, which
the CDK CLI surfaces as a non-zero exit with no template written.

    cdk synth -c env=dev -c budgetEmail=you@example.com
    cdk synth -c env=demo -c budgetEmail=you@example.com
    cdk synth -c env=hackathon -c budgetEmail=you@example.com
"""

import sys
from pathlib import Path

# `cdk synth` runs this file from the infra/ directory, so the repository root
# (which holds the ``infra`` package) must be importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import aws_cdk as cdk  # noqa: E402

from infra.environments import resolve_environment, resolve_region  # noqa: E402
from infra.stacks.api import (  # noqa: E402
    ApiStack,
    resolve_model_id,
    resolve_write_secret,
)
from infra.stacks.budget import BudgetStack, resolve_budget_email  # noqa: E402
from infra.stacks.data import DataStack  # noqa: E402
from infra.stacks.workflow import WorkflowStack  # noqa: E402


def build_app() -> cdk.App:
    app = cdk.App()
    env_name = app.node.try_get_context("env")
    env_config = resolve_environment(env_name)
    region = resolve_region(app.node.try_get_context("region"))
    email = resolve_budget_email(app.node.try_get_context("budgetEmail"))

    account = app.node.try_get_context("account")
    cdk_env = cdk.Environment(account=account, region=region) if account else None

    BudgetStack(
        app,
        f"{env_config.stack_prefix}-Budget",
        env_config=env_config,
        notification_email=email,
        env=cdk_env,
    )

    data = DataStack(
        app,
        f"{env_config.stack_prefix}-Data",
        env_config=env_config,
        env=cdk_env,
    )

    workflow = WorkflowStack(
        app,
        f"{env_config.stack_prefix}-Workflow",
        env_config=env_config,
        incoming_bucket_name=data.buckets["incoming"].bucket_name,
        standardized_bucket_name=data.buckets["standardized"].bucket_name,
        curated_bucket_name=data.buckets["curated"].bucket_name,
        quarantined_bucket_name=data.buckets["quarantined"].bucket_name,
        metadata_table_name=data.metadata_table.table_name,
        glue_database_name=data.glue_database_name,
        region=region,
        env=cdk_env,
    )

    # The public surface is opt-in: it needs a write secret, and synthesizing it
    # requires the API Lambda package to have been built. Skip it unless asked,
    # so `cdk synth` for the data and workflow stacks keeps working on its own.
    if app.node.try_get_context("withApi"):
        ApiStack(
            app,
            f"{env_config.stack_prefix}-Api",
            env_config=env_config,
            incoming_bucket_name=data.buckets["incoming"].bucket_name,
            curated_bucket_name=data.buckets["curated"].bucket_name,
            metadata_bucket_name=data.buckets["metadata"].bucket_name,
            metadata_table_name=data.metadata_table.table_name,
            glue_database_name=data.glue_database_name,
            athena_workgroup_name=data.athena_workgroup_name,
            state_machine_arn=workflow.state_machine.state_machine_arn,
            region=region,
            model_id=resolve_model_id(app.node.try_get_context("modelId")),
            write_secret=resolve_write_secret(app.node.try_get_context("writeSecret")),
            env=cdk_env,
        )

    return app


if __name__ == "__main__":
    build_app().synth()
