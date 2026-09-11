"""ForecastService contract.

Feature: aws-stage1-foundation. Property 8 (unknown key raises).
"""

import pytest

from youth_compass.ports import ForecastRequest, ForecastService, TrainingRequest, TrainingStatus


class TestForecastServiceContract:
    def test_property_8_unknown_forecast_key_raises(
        self, forecast_service: ForecastService
    ) -> None:
        from youth_compass.domain.errors import ForecastNotAvailableError

        with pytest.raises(ForecastNotAvailableError):
            forecast_service.get_forecast(
                ForecastRequest(metric_code="no_such_metric", horizon_years=1)
            )

    def test_get_forecast_returns_points_with_intervals(
        self, forecast_service: ForecastService
    ) -> None:
        result = forecast_service.get_forecast(
            ForecastRequest(metric_code="youth_population", district_codes=["01"], horizon_years=2)
        )
        assert result.model_version
        assert result.points
        for point in result.points:
            assert point.lower <= point.value <= point.upper

    def test_trigger_training_returns_run_with_id_and_active_status(
        self, forecast_service: ForecastService
    ) -> None:
        run = forecast_service.trigger_training(
            TrainingRequest(metric_code="youth_population", training_data_uri="mem://train.parquet")
        )
        assert run.run_id
        assert run.status in {TrainingStatus.QUEUED, TrainingStatus.RUNNING}
