"""In-memory ForecastService reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from tests.contract.registry import register_forecast_service
from youth_compass.domain.errors import ForecastNotAvailableError
from youth_compass.ports import (
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    ForecastService,
    TrainingRequest,
    TrainingRun,
    TrainingStatus,
)

_AVAILABLE_METRICS = {"youth_population"}


class InMemoryForecastService:
    """Returns a fixed forecast for known metrics; queues every training run."""

    def __init__(self) -> None:
        self._counter = 0

    def get_forecast(self, request: ForecastRequest) -> ForecastResult:
        if request.metric_code not in _AVAILABLE_METRICS:
            raise ForecastNotAvailableError(
                f"no forecast artifact for metric {request.metric_code!r}"
            )
        districts = request.district_codes or ["01"]
        points = [
            ForecastPoint(
                district_code=code,
                year_gregorian=2026 + h,
                value=1000.0,
                lower=900.0,
                upper=1100.0,
            )
            for code in districts
            for h in range(request.horizon_years)
        ]
        return ForecastResult(
            metric_code=request.metric_code,
            model_version="reference-v1",
            points=points,
            generated_at=datetime(2026, 9, 12, tzinfo=UTC),
        )

    def trigger_training(self, request: TrainingRequest) -> TrainingRun:
        self._counter += 1
        return TrainingRun(
            run_id=f"run-{self._counter}",
            status=TrainingStatus.QUEUED,
            submitted_at=datetime(2026, 9, 12, tzinfo=UTC),
        )


@register_forecast_service("reference")
@contextmanager
def _reference_forecast_service() -> Iterator[ForecastService]:
    yield InMemoryForecastService()
