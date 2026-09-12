"""Validated application configuration."""

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from youth_compass.domain.errors import ConfigurationError

CONFIG_DIR = Path("configs")


class ProfileSettings(BaseModel):
    """Limits controlling streaming CSV profiling."""

    sample_value_limit: int = Field(default=5, ge=1, le=20)
    distinct_value_cap: int = Field(default=10_000, ge=100)
    duplicate_check_limit: int = Field(default=100_000, ge=1_000)


class TransformSettings(BaseModel):
    """Limits and versioning for deterministic CSV transformation."""

    batch_size: int = Field(default=10_000, ge=100, le=100_000)
    max_rejection_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    transformation_version: str = Field(default="canonical-v1", min_length=1)


# --- Provider selection ------------------------------------------------------
#
# Each Port is satisfied by one Adapter, chosen by configuration rather than
# code, exactly as docs/01-system-architecture.md section 6 specifies. The
# permitted values per Port form a closed set; anything else fails validation.


class StorageProvider(StrEnum):
    FILESYSTEM = "filesystem"
    S3 = "s3"


class CatalogProvider(StrEnum):
    SQLITE = "sqlite"
    GLUE = "glue"


class QueryProvider(StrEnum):
    DUCKDB = "duckdb"
    ATHENA = "athena"


class ModelProviderName(StrEnum):
    OLLAMA = "ollama"
    BEDROCK = "bedrock"


class ForecastProvider(StrEnum):
    LOCAL = "local"
    SAGEMAKER = "sagemaker"


class StorageSettings(BaseModel):
    provider: StorageProvider = StorageProvider.FILESYSTEM
    root: str | None = None
    bucket: str | None = None


class CatalogSettings(BaseModel):
    provider: CatalogProvider = CatalogProvider.SQLITE
    database: str | None = None


class QuerySettings(BaseModel):
    provider: QueryProvider = QueryProvider.DUCKDB
    workgroup: str | None = None


class ModelSettings(BaseModel):
    provider: ModelProviderName = ModelProviderName.OLLAMA
    model_id: str | None = None
    region: str = Field(default="us-east-1", min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    max_attempts: int = Field(default=3, ge=1, le=10)


class ForecastSettings(BaseModel):
    provider: ForecastProvider = ForecastProvider.LOCAL


_LOCAL_ENVIRONMENT = "local"
# The provider-selection keys, and the local default each resolves to when the
# environment is "local" and the key is absent.
_PROVIDER_KEYS: Mapping[str, str] = {
    "storage": StorageProvider.FILESYSTEM.value,
    "catalog": CatalogProvider.SQLITE.value,
    "query": QueryProvider.DUCKDB.value,
    "model": ModelProviderName.OLLAMA.value,
    "forecast": ForecastProvider.LOCAL.value,
}


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` onto ``base`` recursively; a later mapping replaces only
    the keys it supplies, preserving sibling subkeys resolved earlier."""

    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


class AppSettings(BaseSettings):
    """Runtime settings shared by CLI, API, and workers."""

    model_config = SettingsConfigDict(
        env_prefix="YOUTH_COMPASS_",
        env_nested_delimiter="__",
        extra="ignore",
        protected_namespaces=(),
    )

    environment: str = "local"
    data_root: Path = Path("data")
    profile: ProfileSettings = ProfileSettings()
    transform: TransformSettings = TransformSettings()

    storage: StorageSettings | None = None
    catalog: CatalogSettings | None = None
    query: QuerySettings | None = None
    model: ModelSettings | None = None
    forecast: ForecastSettings | None = None

    @model_validator(mode="after")
    def _resolve_provider_selection(self) -> Self:
        """Default absent provider keys under ``local``; require them for a
        non-local environment that engages provider selection.

        A non-local environment "engages provider selection" when it declares at
        least one provider key. This satisfies criterion 10.10 for the case it
        protects -- loading ``environment: aws`` with an incomplete provider set
        must fail -- while leaving a bare environment that selects no providers
        (such as the pre-existing ``environment: test`` fixture) to inherit local
        defaults, so Requirement 2 criterion 16 also holds.
        """

        engaged = any(getattr(self, key) is not None for key in _PROVIDER_KEYS)
        if self.environment == _LOCAL_ENVIRONMENT or not engaged:
            self.storage = self.storage or StorageSettings()
            self.catalog = self.catalog or CatalogSettings()
            self.query = self.query or QuerySettings()
            self.model = self.model or ModelSettings()
            self.forecast = self.forecast or ForecastSettings()
            return self

        missing = [key for key in _PROVIDER_KEYS if getattr(self, key) is None]
        if missing:
            raise ConfigurationError(
                f"non-local environment {self.environment!r} omits required "
                "provider keys: " + ", ".join(sorted(missing))
            )
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "AppSettings":
        """Load a YAML file and then apply environment variable overrides."""

        raw = _read_yaml(path)
        return cls(**raw)

    @classmethod
    def load(
        cls,
        environment: str | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> "AppSettings":
        """Resolve settings through the documented four-source precedence.

        Order, per docs/07-project-structure.md section 9: ``configs/base.yaml``,
        then ``configs/{environment}.yaml``, then ``YOUTH_COMPASS_``-prefixed
        environment variables (applied by ``BaseSettings``), then ``overrides``.
        Each later source replaces only the keys it supplies.
        """

        merged = _read_yaml(CONFIG_DIR / "base.yaml")

        # An explicit environment argument selects, and requires, its YAML file.
        # A base.yaml that merely names its own environment does not, so that
        # loading base.yaml alone continues to resolve.
        if environment is not None:
            env_path = CONFIG_DIR / f"{environment}.yaml"
            if not env_path.exists():
                raise ConfigurationError(
                    f"environment {environment!r} has no configuration file at {env_path}"
                )
            merged = _deep_merge(merged, _read_yaml(env_path))
            merged["environment"] = environment

        if overrides:
            merged = _deep_merge(merged, overrides)
        return cls(**merged)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration root must be a mapping: {path}")
    return loaded


def load_settings(path: Path = Path("configs/base.yaml")) -> AppSettings:
    """Load the default validated application settings."""

    return AppSettings.from_yaml(path)
