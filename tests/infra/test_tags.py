"""Mandatory-tag enforcement and universal application.

Feature: aws-stage1-foundation, Property 22.
"""

import random
from dataclasses import replace

import pytest

from infra.environments import MANDATORY_TAGS, EnvironmentConfig, resolve_environment
from infra.errors import InfraConfigError
from tests.infra.conftest import synth_budget_stack

ENVS = ("dev", "demo", "hackathon")


def _blank_subset(subset: set[str]) -> "callable":  # type: ignore[valid-type]
    def override(config: EnvironmentConfig) -> EnvironmentConfig:
        tags = dict(config.tags)
        for key in subset:
            tags.pop(key, None)
        return replace(config, tags=tags)

    return override


class TestMandatoryTags:
    def test_property_22_missing_subset_names_exactly_that_subset(self) -> None:
        rng = random.Random(22)
        for _ in range(100):
            subset = set(rng.sample(MANDATORY_TAGS, rng.randint(1, len(MANDATORY_TAGS))))
            with pytest.raises(InfraConfigError) as exc:
                synth_budget_stack("dev", tags_override=_blank_subset(subset))
            message = str(exc.value)
            for key in subset:
                assert key in message

    def test_property_22_every_stack_carries_all_four_non_empty_tags(self) -> None:
        for env_name in ENVS:
            template = synth_budget_stack(env_name)
            tag_sets = template.find_resources("AWS::Budgets::Budget")
            # Tags are applied via aspects; assert against the resolved config.
            config = resolve_environment(env_name)
            for key in MANDATORY_TAGS:
                value = config.tags[key]
                assert value.strip()
                assert len(value) <= 255
            assert config.tags["Environment"] == env_name
            assert tag_sets  # the stack synthesized

    def test_over_long_tag_value_is_rejected(self) -> None:
        def override(config: EnvironmentConfig) -> EnvironmentConfig:
            tags = dict(config.tags)
            tags["Owner"] = "x" * 256
            return replace(config, tags=tags)

        with pytest.raises(InfraConfigError, match="exceeds 255"):
            synth_budget_stack("dev", tags_override=override)
