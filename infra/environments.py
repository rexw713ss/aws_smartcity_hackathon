"""Context environments for the CDK application.

Three named environments, each with its own stack prefix, mandatory
cost-allocation tags, and monthly budget threshold. An unknown or absent
environment name is an error, never a silent default, so ``cdk synth`` can never
target the wrong environment.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from infra.errors import InfraConfigError

DEFAULT_REGION = "ap-northeast-1"
MANDATORY_TAGS = ("Project", "Environment", "Owner", "CostCenter")


@dataclass(frozen=True)
class EnvironmentConfig:
    """Resolved configuration for one context environment."""

    name: str
    stack_prefix: str
    budget_usd: int
    tags: Mapping[str, str]


def _config(name: str, budget_usd: int) -> EnvironmentConfig:
    prefix = f"YouthCompass-{name}"
    return EnvironmentConfig(
        name=name,
        stack_prefix=prefix,
        budget_usd=budget_usd,
        tags={
            "Project": "NewTaipeiYouthCompass",
            "Environment": name,
            "Owner": "aws-workstream",
            "CostCenter": "hackathon-2026",
        },
    )


ENVIRONMENTS: Mapping[str, EnvironmentConfig] = {
    "dev": _config("dev", 10),
    "demo": _config("demo", 20),
    "hackathon": _config("hackathon", 50),
}


def resolve_environment(name: str | None) -> EnvironmentConfig:
    """Return the config for ``name``; raise for anything but the three names."""

    config = ENVIRONMENTS.get(name) if name is not None else None
    if config is None:
        accepted = ", ".join(ENVIRONMENTS)
        raise InfraConfigError(f"unknown context environment {name!r}; expected one of: {accepted}")
    return config


def resolve_region(context_region: str | None) -> str:
    """Region precedence: ``-c region`` then ``CDK_DEFAULT_REGION`` then default."""

    if context_region:
        return context_region
    return os.environ.get("CDK_DEFAULT_REGION") or DEFAULT_REGION
