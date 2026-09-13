"""The S3 forecast reader: download once per ETag, refresh on a timer, fail closed."""

import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from moto import mock_aws

from adapters.aws.s3_forecast_artifact import S3ForecastArtifactService, publish_forecast_to_s3
from youth_compass.domain.errors import ForecastNotAvailableError
from youth_compass.ports import ForecastRequest

_BUCKET = "forecasts-bucket"
_PREFIX = "population/"


def _write(directory: Path, value: float, generated: datetime) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "current.parquet"
    pq.write_table(
        pa.table(
            {
                "metric_code": ["population_count"],
                "district_code": ["17"],
                "year_gregorian": [2027],
                "value": [value],
                "lower": [value - 10],
                "upper": [value + 10],
                "model_version": ["cohort-change-ratio-v1"],
                "generated_at": [generated],
            }
        ),
        artifact,
    )
    card = directory / "model-card.json"
    card.write_text(
        json.dumps(
            {
                "model_version": "cohort-change-ratio-v1",
                "generated_at": generated.isoformat(),
                "evaluation": {
                    "method": "cohort",
                    "selected_model": "cohort-change-ratio-v1",
                    "baseline_model": "naive-last-value",
                    "base_period": "2026-07",
                    "target_coverage": 0.8,
                    "error_quantile": 0.9,
                    "candidates": [
                        {
                            "model": "cohort-change-ratio-v1",
                            "accuracy": [
                                {
                                    "horizon_years": 1,
                                    "samples": 10,
                                    "mape_percent": 1.0,
                                    "p90_ape_percent": 2.0,
                                    "bias_percent": 0.1,
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return artifact, card


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def s3():  # type: ignore[no-untyped-def]
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        yield client


def _request() -> ForecastRequest:
    return ForecastRequest(metric_code="population_count", horizon_years=1)


def test_serves_the_published_forecast_with_its_card(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    artifact, card = _write(tmp_path / "run", 100.0, datetime(2026, 9, 1, tzinfo=UTC))
    uris = publish_forecast_to_s3(artifact, card, bucket=_BUCKET, prefix=_PREFIX, client=s3)

    service = S3ForecastArtifactService(_BUCKET, _PREFIX, tmp_path / "cache", client=s3)
    result = service.get_forecast(_request())

    assert uris == (
        f"s3://{_BUCKET}/population/model-card.json",
        f"s3://{_BUCKET}/population/current.parquet",
    )
    assert result.points[0].value == 100.0
    assert result.evaluation is not None


def test_a_new_upload_is_picked_up_after_the_refresh_interval(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    first = _write(tmp_path / "one", 100.0, datetime(2026, 9, 1, tzinfo=UTC))
    publish_forecast_to_s3(*first, bucket=_BUCKET, prefix=_PREFIX, client=s3)
    clock = _Clock()
    service = S3ForecastArtifactService(
        _BUCKET, _PREFIX, tmp_path / "cache", client=s3, refresh_seconds=60, clock=clock
    )
    assert service.get_forecast(_request()).points[0].value == 100.0

    second = _write(tmp_path / "two", 200.0, datetime(2026, 9, 2, tzinfo=UTC))
    publish_forecast_to_s3(*second, bucket=_BUCKET, prefix=_PREFIX, client=s3)
    clock.now = 30
    assert service.get_forecast(_request()).points[0].value == 100.0
    clock.now = 61
    result = service.get_forecast(_request())

    assert result.points[0].value == 200.0
    assert result.evaluation is not None


def test_a_forecast_without_its_card_is_served_without_evidence(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    artifact, _ = _write(tmp_path / "run", 100.0, datetime(2026, 9, 1, tzinfo=UTC))
    s3.upload_file(str(artifact), _BUCKET, f"{_PREFIX}current.parquet")

    result = S3ForecastArtifactService(
        _BUCKET, _PREFIX, tmp_path / "cache", client=s3
    ).get_forecast(_request())

    assert result.evaluation is None


def test_no_artifact_fails_closed(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    service = S3ForecastArtifactService(_BUCKET, _PREFIX, tmp_path / "cache", client=s3)

    with pytest.raises(ForecastNotAvailableError, match="no published forecast artifact"):
        service.get_forecast(_request())
