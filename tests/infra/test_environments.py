"""Environment resolution.

Feature: aws-stage1-foundation, Property 21 (resolution is total and closed).
"""

import random

import pytest

from infra.environments import ENVIRONMENTS, MANDATORY_TAGS, resolve_environment, resolve_region
from infra.errors import InfraConfigError


class TestEnvironmentResolution:
    def test_property_21_three_names_resolve(self) -> None:
        for name in ("dev", "demo", "hackathon"):
            assert resolve_environment(name).name == name

    def test_property_21_anything_else_raises_naming_value_and_accepted(self) -> None:
        rng = random.Random(21)
        bad = ["prod", "staging", "DEV", "", "hackathon ", "test"]
        for _ in range(100):
            name = rng.choice(bad)
            with pytest.raises(InfraConfigError) as exc:
                resolve_environment(name)
            message = str(exc.value)
            assert repr(name) in message
            for accepted in ("dev", "demo", "hackathon"):
                assert accepted in message

    def test_property_21_absent_environment_raises(self) -> None:
        with pytest.raises(InfraConfigError):
            resolve_environment(None)

    def test_property_21_each_entry_is_well_formed(self) -> None:
        for config in ENVIRONMENTS.values():
            assert 1 <= len(config.stack_prefix) <= 32
            assert config.budget_usd > 0
            for tag in MANDATORY_TAGS:
                assert config.tags.get(tag, "").strip()

    def test_budget_thresholds_are_the_documented_literals(self) -> None:
        assert resolve_environment("dev").budget_usd == 10
        assert resolve_environment("demo").budget_usd == 20
        assert resolve_environment("hackathon").budget_usd == 50


class TestRegionResolution:
    def test_context_region_wins(self) -> None:
        assert resolve_region("us-east-1") == "us-east-1"

    def test_env_var_is_next(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CDK_DEFAULT_REGION", "eu-west-1")
        assert resolve_region(None) == "eu-west-1"

    def test_default_is_tokyo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CDK_DEFAULT_REGION", raising=False)
        assert resolve_region(None) == "ap-northeast-1"
