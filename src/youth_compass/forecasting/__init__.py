"""Forecasting: the log-linear baseline and the cohort change ratio model."""

from youth_compass.forecasting.baseline import (
    MODEL_VERSION,
    ForecastInputError,
    ForecastPointValue,
    forecast_series,
)

__all__ = [
    "MODEL_VERSION",
    "ForecastInputError",
    "ForecastPointValue",
    "forecast_series",
]
