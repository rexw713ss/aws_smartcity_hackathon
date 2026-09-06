"""Shared synthesis helpers for the infra tests.

Every stack is synthesized with an explicit placeholder account and region so no
AWS credential is read.
"""

from collections.abc import Callable

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.environments import EnvironmentConfig, resolve_environment
from infra.stacks.budget import BudgetStack
from tests.infra.constants import PLACEHOLDER_ACCOUNT, PLACEHOLDER_EMAIL, PLACEHOLDER_REGION


def synth_budget_stack(
    env_name: str,
    *,
    email: str = PLACEHOLDER_EMAIL,
    tags_override: Callable[[EnvironmentConfig], EnvironmentConfig] | None = None,
) -> Template:
    """Synthesize the budget stack for ``env_name`` and return its Template."""

    app = cdk.App()
    config = resolve_environment(env_name)
    if tags_override is not None:
        config = tags_override(config)
    stack = BudgetStack(
        app,
        f"{config.stack_prefix}-Budget",
        env_config=config,
        notification_email=email,
        env=cdk.Environment(account=PLACEHOLDER_ACCOUNT, region=PLACEHOLDER_REGION),
    )
    return Template.from_stack(stack)
