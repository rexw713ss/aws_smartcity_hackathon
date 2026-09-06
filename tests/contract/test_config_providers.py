"""Provider-selection configuration.

Feature: aws-stage1-foundation
Property 50 (closed set per Port), 51 (environment gates optionality),
52 (recursive precedence), 53 (documented files match the architecture record).
"""

import os
import random
from pathlib import Path

import pytest

from youth_compass.config import CONFIG_DIR, AppSettings, _deep_merge
from youth_compass.domain.errors import ConfigurationError

# docs/01-system-architecture.md section 6.
DOCUMENTED = {
    "local": {
        "storage": "filesystem",
        "catalog": "sqlite",
        "query": "duckdb",
        "model": "ollama",
        "forecast": "local",
    },
    "aws": {
        "storage": "s3",
        "catalog": "glue",
        "query": "athena",
        "model": "bedrock",
        "forecast": "sagemaker",
    },
}

PERMITTED = {
    "storage": ("filesystem", "s3"),
    "catalog": ("sqlite", "glue"),
    "query": ("duckdb", "athena"),
    "model": ("ollama", "bedrock"),
    "forecast": ("local", "sagemaker"),
}


def _providers(settings: AppSettings) -> dict[str, str]:
    return {
        key: str(getattr(settings, key).provider)
        for key in ("storage", "catalog", "query", "model", "forecast")
    }


# --- Property 53: documented files load and match the architecture record ----


@pytest.mark.parametrize("environment", ("local", "aws"))
def test_property_53_documented_files_match_docs_01(environment: str) -> None:
    example = "aws.example" if environment == "aws" else environment
    path = CONFIG_DIR / f"{example}.yaml"
    assert path.exists(), path
    settings = AppSettings.from_yaml(path)
    assert _providers(settings) == DOCUMENTED[environment]


def test_config_files_exist_at_expected_paths() -> None:
    assert (CONFIG_DIR / "local.yaml").exists()
    assert (CONFIG_DIR / "aws.example.yaml").exists()


# --- Requirement 10.7: local loads with no AWS environment variables ---------


def test_local_loads_with_aws_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_REGION",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = AppSettings.from_yaml(CONFIG_DIR / "local.yaml")
    assert _providers(settings) == DOCUMENTED["local"]


# --- Property 50: closed permitted set per Port ------------------------------


def test_property_50_permitted_values_resolve() -> None:
    for key, values in PERMITTED.items():
        for value in values:
            env = "local" if value == DOCUMENTED["local"][key] else "aws"
            payload: dict[str, object] = {"environment": env, key: {"provider": value}}
            if env == "aws":
                for other in PERMITTED:
                    payload.setdefault(other, {"provider": DOCUMENTED["aws"][other]})
            settings = AppSettings(**payload)
            assert str(getattr(settings, key).provider) == value


def test_property_50_outside_values_are_rejected_naming_key() -> None:
    rng = random.Random(1234)
    bad_tokens = ["nfs", "postgres", "spark", "vertex", "", "S3", "Filesystem"]
    for _ in range(100):
        key = rng.choice(list(PERMITTED))
        token = rng.choice(bad_tokens)
        with pytest.raises(Exception) as exc:
            AppSettings(environment="local", **{key: {"provider": token}})
        message = str(exc.value)
        assert key in message or "provider" in message


# --- Property 51: environment gates provider-key optionality -----------------


def test_property_51_local_defaults_absent_keys() -> None:
    rng = random.Random(51)
    keys = list(PERMITTED)
    for _ in range(100):
        present = {k: {"provider": DOCUMENTED["local"][k]} for k in keys if rng.random() < 0.5}
        settings = AppSettings(environment="local", **present)
        assert _providers(settings) == DOCUMENTED["local"]


def test_property_51_non_local_requires_all_keys_naming_omissions() -> None:
    rng = random.Random(510)
    keys = list(PERMITTED)
    for _ in range(100):
        # Omit a proper, non-empty subset so at least one provider key remains,
        # which is what "engages provider selection" means and what 10.10 guards.
        omit = set(rng.sample(keys, rng.randint(1, len(keys) - 1)))
        present = {k: {"provider": DOCUMENTED["aws"][k]} for k in keys if k not in omit}
        with pytest.raises(ConfigurationError) as exc:
            AppSettings(environment="aws", **present)
        message = str(exc.value)
        for key in omit:
            assert key in message


def test_property_51_missing_environment_file_names_env_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "base.yaml").write_text("environment: local\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as exc:
        AppSettings.load(environment="staging")
    assert "staging" in str(exc.value)
    assert "configs/staging.yaml" in str(exc.value).replace(os.sep, "/")


# --- Property 52: recursive four-source precedence ---------------------------


def test_property_52_deep_merge_resolves_per_key_recursively() -> None:
    rng = random.Random(52)
    for _ in range(100):
        base = {"a": {"x": rng.randint(0, 9), "y": rng.randint(0, 9)}, "b": rng.randint(0, 9)}
        overlay = {"a": {"y": rng.randint(10, 19)}, "c": rng.randint(10, 19)}
        merged = _deep_merge(base, overlay)
        # overlay wins where it supplies a key
        assert merged["a"]["y"] == overlay["a"]["y"]
        assert merged["c"] == overlay["c"]
        # sibling not supplied by overlay is preserved
        assert merged["a"]["x"] == base["a"]["x"]
        assert merged["b"] == base["b"]


def test_property_52_load_applies_overrides_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "base.yaml").write_text(
        "environment: local\nprofile:\n  sample_value_limit: 5\n", encoding="utf-8"
    )
    settings = AppSettings.load(overrides={"profile": {"sample_value_limit": 9}})
    assert settings.profile.sample_value_limit == 9
    # unsupplied sibling keeps its default
    assert settings.profile.distinct_value_cap == 10_000
