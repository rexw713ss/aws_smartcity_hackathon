"""Baseline forecasting: a deterministic log-linear trend with uncertainty."""

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
