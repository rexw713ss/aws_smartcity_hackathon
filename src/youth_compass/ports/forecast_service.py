"""ForecastService port and its payload models.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.5.

Every forecast carries an uncertainty interval and a model version, because
docs/README.md makes both non-negotiable for any published forecast.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class TrainingStatus(StrEnum):
    """Lifecycle of a training run."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ForecastRequest(BaseModel):
    """A request for published forecast values."""

    metric_code: str
    district_codes: list[str] = Field(default_factory=list)
    horizon_years: int = Field(ge=1, le=20)
    as_of: date | None = None


class ForecastPoint(BaseModel):
    """One forecast value with its uncertainty interval."""

    district_code: str
    year_gregorian: int
    value: float
    lower: float
    upper: float

    @model_validator(mode="after")
    def _validate_interval(self) -> "ForecastPoint":
        if not self.lower <= self.value <= self.upper:
            raise ValueError("forecast interval must contain the point estimate")
        return self


class ForecastResult(BaseModel):
    """Forecast values and the lineage needed to judge them."""

    metric_code: str
    model_version: str
    points: list[ForecastPoint] = Field(min_length=1)
    generated_at: AwareDatetime


class TrainingRequest(BaseModel):
    """A request to train a new candidate model."""

    metric_code: str
    training_data_uri: str
    hyperparameters: dict[str, str] = Field(default_factory=dict)


class TrainingRun(BaseModel):
    """A submitted training run."""

    run_id: str = Field(min_length=1)
    status: TrainingStatus
    submitted_at: datetime
    artifact_uri: str | None = None


@runtime_checkable
class ForecastService(Protocol):
    """Published forecast retrieval and training submission."""

    def get_forecast(self, request: ForecastRequest) -> ForecastResult:
        """Return the published forecast satisfying ``request``.

        Raises:
            ForecastNotAvailableError: no forecast artifact exists for the key.
        """
        ...

    def trigger_training(self, request: TrainingRequest) -> TrainingRun:
        """Submit a training run and return its reference.

        Raises:
            TrainingRejectedError: the request was refused before a run existed.
        """
        ...
