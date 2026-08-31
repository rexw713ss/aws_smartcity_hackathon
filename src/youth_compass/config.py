"""Validated application configuration."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProfileSettings(BaseModel):
    """Limits controlling streaming CSV profiling."""

    sample_value_limit: int = Field(default=5, ge=1, le=20)
    distinct_value_cap: int = Field(default=10_000, ge=100)
    duplicate_check_limit: int = Field(default=100_000, ge=1_000)


class AppSettings(BaseSettings):
    """Runtime settings shared by CLI, API, and workers."""

    model_config = SettingsConfigDict(
        env_prefix="YOUTH_COMPASS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: str = "local"
    data_root: Path = Path("data")
    profile: ProfileSettings = ProfileSettings()

    @classmethod
    def from_yaml(cls, path: Path) -> "AppSettings":
        """Load a YAML file and then apply environment variable overrides."""

        raw: dict[str, Any] = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if loaded is not None:
                if not isinstance(loaded, dict):
                    raise ValueError(f"Configuration root must be a mapping: {path}")
                raw = loaded
        return cls(**raw)


def load_settings(path: Path = Path("configs/base.yaml")) -> AppSettings:
    """Load the default validated application settings."""

    return AppSettings.from_yaml(path)
