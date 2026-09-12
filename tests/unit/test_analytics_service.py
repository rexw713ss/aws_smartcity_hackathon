from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from adapters.local import DuckDBQueryEngine
from youth_compass.analytics import CuratedAnalyticsService
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)
from youth_compass.domain.errors import AnalyticsNotAvailableError

_DIMENSIONS = {
    "age_lower",
    "age_upper",
    "gender_code",
    "year_gregorian",
    "month",
    "district_code",
    "district_name",
    "metric_code",
    "unit_code",
    "population_scope",
    "is_estimated",
}


def _service(tmp_path: Path) -> CuratedAnalyticsService:
    parquet = tmp_path / "population.parquet"
    pq.write_table(
        pa.table(
            {
                "year_gregorian": [2024, 2025, 2025, 2025],
                "month": [12, 1, 1, 1],
                "district_code": ["01", "01", "01", "02"],
                "district_name": ["板橋區", "板橋區", "板橋區", "三重區"],
                "metric_code": ["population_count"] * 4,
                "unit_code": ["persons"] * 4,
                "population_scope": ["youth_specific"] * 4,
                "is_estimated": [False, False, True, False],
                "age_lower": [18, 18, 21, 18],
                "age_upper": [18, 18, 21, 18],
                "gender_code": ["male", "male", "female", "female"],
                "metric_value": [90.0, 100.0, 40.0, 80.0],
            }
        ),
        parquet,
    )
    engine = DuckDBQueryEngine(
        tables={"population": parquet},
        allowed_metrics={"metric_value"},
        allowed_dimensions=_DIMENSIONS,
    )
    metadata = DatasetMetadata(
        dataset_id="population",
        version="v1",
        source_uri="fileobj://incoming/population.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code", "age_lower"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.97,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    return CuratedAnalyticsService(engine, metadata)


def test_city_summary_uses_latest_period_and_carries_evidence(tmp_path: Path) -> None:
    summary = _service(tmp_path).city_summary("population_count")

    assert summary.period == "2025-01"
    assert summary.value == 220.0
    assert summary.estimated_value == 40.0
    assert summary.district_count == 2
    assert summary.dataset_version == "v1"
    assert summary.population_scope == "youth_specific"
    assert summary.quality_score == 0.97


def test_district_profile_aggregates_and_filters_requested_codes(tmp_path: Path) -> None:
    profile = _service(tmp_path).district_profile(
        "population_count", district_codes=["01"], period="2025-01"
    )

    assert len(profile.districts) == 1
    assert profile.districts[0].district_name == "板橋區"
    assert profile.districts[0].value == 140.0
    assert profile.districts[0].estimated_value == 40.0


def test_analytics_rejects_bad_period_and_missing_district(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(AnalyticsNotAvailableError, match="YYYY"):
        service.city_summary("population_count", period="2025/01")
    with pytest.raises(AnalyticsNotAvailableError, match="district codes"):
        service.district_profile("population_count", district_codes=["99"])


def test_district_overview_returns_chart_ready_trend_and_shares(tmp_path: Path) -> None:
    overview = _service(tmp_path).district_overview("01")

    assert overview.period == "2025-01"
    assert overview.total == 140
    assert overview.previous_period == "2024-12"
    assert overview.absolute_change == 50
    assert overview.percent_change == 55.56
    assert [point.value for point in overview.trend] == [90, 140]
    assert [(item.label, item.share_percent) for item in overview.age_distribution] == [
        ("18-20", 71.4),
        ("21-24", 28.6),
    ]
    assert [(item.label, item.share_percent) for item in overview.gender_distribution] == [
        ("Male", 71.4),
        ("Female", 28.6),
    ]
