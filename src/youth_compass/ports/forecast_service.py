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


class ForecastComponents(BaseModel):
    """Why a cohort forecast moves: ageing in, ageing out, and everything else.

    ``net_change`` is what remains after ageing — migration, mortality, and
    registration changes together — so it must never be presented as migration
    alone.
    """

    base_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    base_value: float = Field(ge=0)
    entering: float = Field(ge=0)
    ageing_out: float = Field(ge=0)
    net_change: float


class ForecastPoint(BaseModel):
    """One forecast value with its uncertainty interval."""

    district_code: str
    year_gregorian: int
    value: float
    lower: float
    upper: float
    components: ForecastComponents | None = None
    # True when the area is small enough that forecast errors are known to rise
    # sharply (fewer than 10,000 residents; Wilson et al. 2021).
    small_area: bool | None = None

    @model_validator(mode="after")
    def _validate_interval(self) -> "ForecastPoint":
        if not self.lower <= self.value <= self.upper:
            raise ValueError("forecast interval must contain the point estimate")
        return self


class ForecastAccuracy(BaseModel):
    """Backtest error of one model at one horizon, in percent of the actual value."""

    horizon_years: int = Field(ge=1)
    samples: int = Field(ge=1)
    mape_percent: float = Field(ge=0)
    p90_ape_percent: float = Field(ge=0)
    bias_percent: float
    # Pseudo-real-time share of outcomes inside the published interval method,
    # reported for the selected model only.
    interval_coverage: float | None = Field(default=None, ge=0, le=1)


class CandidateEvaluation(BaseModel):
    """One backtested model and its accuracy by horizon."""

    model: str = Field(min_length=1)
    accuracy: list[ForecastAccuracy] = Field(min_length=1)


class ForecastEvaluation(BaseModel):
    """The evidence a published forecast was selected on."""

    method: str = Field(min_length=1)
    selected_model: str = Field(min_length=1)
    baseline_model: str = Field(min_length=1)
    base_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    # Intervals aim to contain ``target_coverage`` of outcomes; their half-width is
    # the ``error_quantile`` of past absolute percentage errors.
    target_coverage: float = Field(gt=0, lt=1)
    error_quantile: float = Field(gt=0, lt=1)
    # Measured in pseudo-real time: each interval built only from errors observable
    # at its origin. None when the backtest is too short to measure.
    rolling_coverage: float | None = Field(default=None, ge=0, le=1)
    rolling_samples: int | None = Field(default=None, ge=1)
    small_area_coverage: float | None = Field(default=None, ge=0, le=1)
    candidates: list[CandidateEvaluation] = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    references: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def accuracy_of(self, model: str, horizon_years: int) -> ForecastAccuracy | None:
        for candidate in self.candidates:
            if candidate.model == model:
                for item in candidate.accuracy:
                    if item.horizon_years == horizon_years:
                        return item
        return None


class ForecastResult(BaseModel):
    """Forecast values and the lineage needed to judge them."""

    metric_code: str
    model_version: str
    points: list[ForecastPoint] = Field(min_length=1)
    generated_at: AwareDatetime
    evaluation: ForecastEvaluation | None = None


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
