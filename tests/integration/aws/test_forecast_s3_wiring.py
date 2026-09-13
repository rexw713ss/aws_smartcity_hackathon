"""The API runtime reads the published forecast from S3 when so configured.

Feature: youth population forecast (docs/31), phase 2. The deployed API sets
``forecast.provider: s3``; without it the forecast tool was advertised against a
local file the Lambda package never contained.
"""

from pathlib import Path

import pytest

from adapters.aws.s3_forecast_artifact import S3ForecastArtifactService
from apps.api.dependencies import LocalRuntime
from youth_compass.config import AppSettings, ForecastProvider, ForecastSettings
from youth_compass.domain.errors import ConfigurationError


def test_the_s3_provider_builds_the_s3_reader_and_advertises_the_tool(tmp_path: Path) -> None:
    runtime = LocalRuntime(
        tmp_path / "data",
        settings=AppSettings(
            environment="local",
            forecast=ForecastSettings(
                provider=ForecastProvider.S3, bucket="forecasts-bucket", prefix="population/"
            ),
        ),
    )

    copilot = runtime.copilot()

    assert isinstance(copilot._observations._forecast, S3ForecastArtifactService)
    assert "forecast_metric" in {item.name for item in copilot.list_capabilities()}


def test_the_s3_provider_without_a_bucket_fails_at_startup(tmp_path: Path) -> None:
    runtime = LocalRuntime(
        tmp_path / "data",
        settings=AppSettings(
            environment="local", forecast=ForecastSettings(provider=ForecastProvider.S3)
        ),
    )

    with pytest.raises(ConfigurationError, match=r"forecast\.bucket"):
        runtime.copilot()
