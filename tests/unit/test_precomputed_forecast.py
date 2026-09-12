"""Read-only retrieval from a published local forecast artifact."""

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from adapters.local import PrecomputedParquetForecastService
from youth_compass.domain import ForecastNotAvailableError, TrainingRejectedError
from youth_compass.ports import ForecastRequest, TrainingRequest


def _write_forecast(path: Path, *, invalid_interval: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime(2026, 9, 1, tzinfo=UTC)
    pq.write_table(
        pa.table(
            {
                "metric_code": ["population_count"] * 6,
                "district_code": ["banqiao"] * 3 + ["linkou"] * 3,
                "year_gregorian": [2027, 2028, 2029] * 2,
                "value": [121.0, 122.0, 123.0, 71.0, 70.0, 69.0],
                "lower": [124.0 if invalid_interval else 115.0, 116.0, 117.0, 65.0, 64.0, 63.0],
                "upper": [127.0, 128.0, 129.0, 77.0, 76.0, 75.0],
                "model_version": ["seasonal-naive-v1"] * 6,
                "generated_at": [generated] * 6,
            }
        ),
        path,
    )


def test_returns_requested_district_and_horizon_with_lineage(tmp_path: Path) -> None:
    artifact = tmp_path / "current.parquet"
    _write_forecast(artifact)
    service = PrecomputedParquetForecastService(artifact)

    result = service.get_forecast(
        ForecastRequest(
            metric_code="population_count",
            district_codes=["banqiao"],
            horizon_years=2,
            as_of=date(2026, 9, 12),
        )
    )

    assert result.model_version == "seasonal-naive-v1"
    assert [point.year_gregorian for point in result.points] == [2027, 2028]
    assert all(point.district_code == "banqiao" for point in result.points)
    assert result.generated_at.tzinfo is not None


def test_missing_district_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "current.parquet"
    _write_forecast(artifact)

    with pytest.raises(ForecastNotAvailableError, match="unknown"):
        PrecomputedParquetForecastService(artifact).get_forecast(
            ForecastRequest(
                metric_code="population_count",
                district_codes=["unknown"],
                horizon_years=1,
            )
        )


def test_invalid_uncertainty_interval_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "current.parquet"
    _write_forecast(artifact, invalid_interval=True)

    with pytest.raises(ForecastNotAvailableError, match="invalid values"):
        PrecomputedParquetForecastService(artifact).get_forecast(
            ForecastRequest(
                metric_code="population_count",
                district_codes=["banqiao"],
                horizon_years=1,
            )
        )


def test_read_only_adapter_rejects_live_training(tmp_path: Path) -> None:
    service = PrecomputedParquetForecastService(tmp_path / "current.parquet")

    with pytest.raises(TrainingRejectedError, match="read-only"):
        service.trigger_training(
            TrainingRequest(
                metric_code="population_count",
                training_data_uri="file:///training.parquet",
            )
        )
