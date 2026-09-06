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
from infra.stacks.budget import BudgetStack, resolve_budget_email  # noqa: E402
from infra.stacks.data import DataStack  # noqa: E402


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

    DataStack(
        app,
        f"{env_config.stack_prefix}-Data",
        env_config=env_config,
        env=cdk_env,
    )

    return app


if __name__ == "__main__":
    build_app().synth()
