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


def test_brave_web_search_settings_support_secret_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUTH_COMPASS_WEB_SEARCH__ENABLED", "true")
    monkeypatch.setenv("YOUTH_COMPASS_WEB_SEARCH__API_KEY", "brave-test-key")
    settings = AppSettings()

    assert settings.web_search.enabled is True
    assert settings.web_search.api_key is not None
    assert settings.web_search.api_key.get_secret_value() == "brave-test-key"
    assert "brave-test-key" not in repr(settings.web_search)


def test_brave_environment_overrides_disabled_yaml_for_local_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("web_search:\n  enabled: false\n  result_limit: 3\n", encoding="utf-8")
    monkeypatch.setenv("YOUTH_COMPASS_WEB_SEARCH__ENABLED", "true")
    monkeypatch.setenv("YOUTH_COMPASS_WEB_SEARCH__API_KEY", "brave-test-key")

    settings = AppSettings.from_yaml(path)

    assert settings.web_search.enabled is True
    assert settings.web_search.api_key is not None
    assert settings.web_search.api_key.get_secret_value() == "brave-test-key"
    assert settings.web_search.result_limit == 3
