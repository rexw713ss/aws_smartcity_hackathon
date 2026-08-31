from pathlib import Path

from youth_compass.config import AppSettings


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


def test_missing_yaml_uses_defaults(tmp_path: Path) -> None:
    settings = AppSettings.from_yaml(tmp_path / "missing.yaml")
    assert settings.environment == "local"
    assert settings.data_root == Path("data")
