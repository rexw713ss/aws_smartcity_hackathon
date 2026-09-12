"""Validated application configuration."""

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from youth_compass.domain.errors import ConfigurationError
from youth_compass.ports import SourceCandidate

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

    # Which stages the model is allowed to run. The two carry very different
    # risk: the answer composer only verbalizes a payload the application has
    # already grounded, and its output is rejected if it invents a citation or a
    # number. The query decomposer chooses which tools run, so a plausible but
    # wrong plan routes the whole answer wrong — and a plan that is merely wrong
    # rather than invalid never triggers the deterministic fallback.
    #
    # Measured on evals/agent-routing.jsonl and against the live API: model
    # decomposition currently degrades answers, so it is off by default and must
    # be enabled deliberately.
    compose_answers: bool = True
    decompose_queries: bool = False


class ForecastSettings(BaseModel):
    provider: ForecastProvider = ForecastProvider.LOCAL


class AcquisitionSettings(BaseModel):
    """Allowlisted external-source acquisition policy."""

    enabled: bool = False
    connector_id: str = Field(default="configured_http", pattern=r"^[a-z][a-z0-9_-]*$")
    allowed_hosts: tuple[str, ...] = ()
    max_download_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    timeout_seconds: float = Field(default=20.0, gt=0.0, le=120.0)
    result_limit: int = Field(default=5, ge=1, le=20)
    sources: tuple[SourceCandidate, ...] = ()

    @model_validator(mode="after")
    def _validate_enabled_connector(self) -> Self:
        if self.enabled and (not self.allowed_hosts or not self.sources):
            raise ValueError("enabled acquisition requires allowed_hosts and sources")
        mismatched = [
            source.candidate_id
            for source in self.sources
            if source.connector_id != self.connector_id
        ]
        if mismatched:
            raise ValueError(
                "acquisition sources use a different connector_id: " + ", ".join(mismatched)
            )
        return self


class ApiSettings(BaseModel):
    """HTTP surface settings that only matter once the API is deployed.

    Both fields default to "closed": no cross-origin caller is allowed and no
    write token is configured. The deployment stack supplies real values.
    """

    # Browsers refuse cross-origin calls unless the API echoes the origin back,
    # so a deployed frontend on a different host needs its origin listed here.
    #
    # Held as a comma-separated string rather than a sequence on purpose:
    # pydantic-settings JSON-decodes complex field types read from the
    # environment, so a plain `https://a,https://b` value could never populate a
    # tuple field. Lambda environment variables are always strings. Use
    # ``allowed_origins`` to read the parsed form.
    cors_allowed_origins: str = ""
    # Shared secret required by the mutating endpoints. When unset the guard is
    # inactive, which keeps local development and the test suite unchanged.
    write_secret: str | None = None

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _join_origins(cls, value: object) -> object:
        """Accept a YAML list as well as the environment's comma-separated form."""
        if isinstance(value, list | tuple):
            return ",".join(str(item) for item in value)
        return value

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """The configured origins, empty when nothing is allowed."""
        return tuple(part.strip() for part in self.cors_allowed_origins.split(",") if part.strip())


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
    acquisition: AcquisitionSettings = AcquisitionSettings()
    api: ApiSettings = ApiSettings()

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
