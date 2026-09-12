from pathlib import Path

import pytest

from youth_compass.config import AppSettings, ModelProviderName


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "environment: test\ndata_root: custom-data\nprofile:\n  sample_value_limit: 7\n",
        encoding="utf-8",
    )
    settings = AppSettings.from_yaml(path)
    assert settings.environment == "test"
    assert settings.data_root == Path("custom-data")
    assert settings.profile.sample_value_limit == 7
    assert settings.transform.transformation_version == "canonical-v1"


def test_missing_yaml_uses_defaults(tmp_path: Path) -> None:
    settings = AppSettings.from_yaml(tmp_path / "missing.yaml")
    assert settings.environment == "local"
    assert settings.data_root == Path("data")
    assert settings.transform.batch_size == 10_000


def test_bedrock_model_settings_support_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUTH_COMPASS_MODEL__PROVIDER", "bedrock")
    monkeypatch.setenv("YOUTH_COMPASS_MODEL__MODEL_ID", "test-inference-profile")
    monkeypatch.setenv("YOUTH_COMPASS_MODEL__REGION", "us-east-1")
    monkeypatch.setenv("YOUTH_COMPASS_MODEL__TIMEOUT_SECONDS", "45")
    settings = AppSettings()

    assert settings.model is not None
    assert settings.model.provider is ModelProviderName.BEDROCK
    assert settings.model.model_id == "test-inference-profile"
    assert settings.model.region == "us-east-1"
    assert settings.model.timeout_seconds == 45
