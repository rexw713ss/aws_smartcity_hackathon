"""BudgetStack: one AWS Budgets monthly cost budget with two notifications.

Contains no construct for Amazon Bedrock, Amazon SageMaker AI, or Amazon Bedrock
AgentCore, and none of the five always-on resource types. The notification
address comes from a context key or an environment variable and never from a
committed file.
"""

import os
from typing import Any

from aws_cdk import aws_budgets as budgets
from constructs import Construct

from infra.environments import EnvironmentConfig
from infra.errors import InfraConfigError
from infra.stacks.base import TaggedStack

_CONTEXT_KEY = "budgetEmail"
_ENV_VAR = "YOUTH_COMPASS_BUDGET_EMAIL"


def resolve_budget_email(context_value: str | None) -> str:
    """Context key preferred, then the environment variable; validated."""

    value = context_value or os.environ.get(_ENV_VAR)
    if not value or "@" not in value:
        raise InfraConfigError(
            "budget notification address is missing or invalid; set the CDK "
            f"context key -c {_CONTEXT_KEY}=you@example.com or the environment "
            f"variable {_ENV_VAR}"
        )
    return value


class BudgetStack(TaggedStack):
    """A single monthly cost budget alarming at 80% and 100% of the threshold."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_config: EnvironmentConfig,
        notification_email: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, tags=env_config.tags, **kwargs)

        notifications = [
            budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN",
                    notification_type="ACTUAL",
                    threshold=float(threshold),
                    threshold_type="PERCENTAGE",
                ),
                subscribers=[
                    budgets.CfnBudget.SubscriberProperty(
                        address=notification_email,
                        subscription_type="EMAIL",
                    )
                ],
            )
            for threshold in (80, 100)
        ]

        budgets.CfnBudget(
            self,
            "MonthlyCostBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=float(env_config.budget_usd),
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=notifications,
        )
