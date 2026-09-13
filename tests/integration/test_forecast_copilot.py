"""The copilot's forecast turn: history, drivers, evidence, and the accuracy focus.

Feature: youth population forecast (docs/31). A published monthly dataset and a
cohort artifact with its model card are served through the real API.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from apps.api.main import create_app
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)

_GENERATED = datetime(2026, 9, 1, tzinfo=UTC)


def _publish_observations(data_root: Path) -> DatasetMetadata:
    destination = data_root / "curated" / "youth_population" / "version=v1"
    destination.mkdir(parents=True)
    rows = [
        (year, month, code, value + year - 2021 + (500 if month == 12 else 0))
        for year in range(2021, 2027)
        for month in (7, 12)
        for code, value in (("01", 1000.0), ("17", 800.0))
        if not (year == 2026 and month == 12)
    ]
    pq.write_table(
        pa.table(
            {
                "year_gregorian": [row[0] for row in rows],
                "month": [row[1] for row in rows],
                "city_code": ["ntpc"] * len(rows),
                "city_name": ["New Taipei City"] * len(rows),
                "district_code": [row[2] for row in rows],
                "district_name": ["Banqiao" if row[2] == "01" else "Linkou" for row in rows],
                "metric_code": ["population_count"] * len(rows),
                "unit_code": ["persons"] * len(rows),
                "population_scope": ["youth_specific"] * len(rows),
                "is_estimated": [False] * len(rows),
                "age_lower": [18] * len(rows),
                "age_upper": [35] * len(rows),
                "gender_code": ["female"] * len(rows),
                "metric_value": [row[3] for row in rows],
            }
        ),
        destination / "part-000.parquet",
    )
    return DatasetMetadata(
        dataset_id="youth_population",
        version="v1",
        source_uri="fileobj://incoming/youth-population.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "month", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.98,
        created_at=_GENERATED,
        published_at=_GENERATED,
    )


def _publish_forecast(data_root: Path) -> None:
    directory = data_root / "forecasts"
    directory.mkdir()
    years = [2027, 2028]
    codes = ["01", "17"]
    count = len(years) * len(codes)
    pq.write_table(
        pa.table(
            {
                "metric_code": ["population_count"] * count,
                "district_code": [code for code in codes for _ in years],
                "year_gregorian": years * len(codes),
                "value": [990.0, 980.0, 790.0, 780.0],
                "lower": [970.0, 950.0, 770.0, 750.0],
                "upper": [1010.0, 1010.0, 810.0, 810.0],
                "model_version": ["cohort-change-ratio-v1"] * count,
                "generated_at": [_GENERATED] * count,
                "base_period": ["2026-07"] * count,
                "base_value": [1005.0, 1005.0, 805.0, 805.0],
                "entering": [40.0, 80.0, 30.0, 60.0],
                "ageing_out": [60.0, 110.0, 50.0, 90.0],
                "net_change": [5.0, 5.0, 5.0, 5.0],
                "size_class": ["standard", "standard", "small", "small"],
                "total_population": [300000.0] * 2 + [9000.0] * 2,
            }
        ),
        directory / "current.parquet",
    )
    accuracy = [
        {
            "horizon_years": horizon,
            "samples": 100,
            "mape_percent": horizon * mape,
            "p90_ape_percent": horizon * mape * 2,
            "bias_percent": 0.2,
            "interval_coverage": coverage,
        }
        for horizon in (1, 2)
        for mape, coverage in [(0.8, 0.85)]
    ]
    card = {
        "model_version": "cohort-change-ratio-v1",
        "generated_at": _GENERATED.isoformat(),
        "evaluation": {
            "method": "Hamilton-Perry cohort change ratios",
            "selected_model": "cohort-change-ratio-v1",
            "baseline_model": "naive-last-value",
            "base_period": "2026-07",
            "target_coverage": 0.8,
            "error_quantile": 0.9,
            "rolling_coverage": 0.855,
            "rolling_samples": 200,
            "small_area_coverage": 0.82,
            "candidates": [
                {"model": "cohort-change-ratio-v1", "accuracy": accuracy},
                {
                    "model": "naive-last-value",
                    "accuracy": [
                        {
                            **item,
                            "mape_percent": item["mape_percent"] * 3,
                            "interval_coverage": None,
                        }
                        for item in accuracy
                    ],
                },
            ],
        },
    }
    (directory / "model-card.json").write_text(json.dumps(card), encoding="utf-8")


def _client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    app.state.runtime.catalog.register(_publish_observations(tmp_path))
    _publish_forecast(tmp_path)
    return TestClient(app)


def test_a_forecast_is_drawn_after_its_observed_same_month_history(tmp_path: Path) -> None:
    body = (
        _client(tmp_path)
        .post(
            "/api/v1/copilot/query",
            json={"question": "Forecast the youth population of Linkou for the next 2 years"},
        )
        .json()
    )

    assert body["status"] == "answered"
    history = next(item for item in body["tool_trace"] if item["tool"] == "query_observations")
    assert history["outcome"] == "ok"
    line = next(item for item in body["visualizations"] if item["type"] == "line")
    observed = [row for row in line["rows"] if row["kind"] == "observed"]
    # Only July values, the forecast's snapshot month, precede the projection.
    assert [row["value"] for row in observed] == [800.0, 801.0, 802.0, 803.0, 804.0, 805.0]
    assert all(row["lower"] == row["value"] == row["upper"] for row in observed)
    assert [row["period"] for row in line["rows"] if row["kind"] == "forecast"] == ["2027", "2028"]
    drivers = next(item for item in body["visualizations"] if item["type"] == "contribution_bar")
    assert [row["persons"] for row in drivers["rows"]] == [60.0, -90.0, 5.0]
    assert body["forecast_result"]["evaluation"]["rolling_coverage"] == 0.855
    assert any("fewer than 10,000 residents" in item for item in body["warnings"])


def test_an_accuracy_question_leads_with_the_backtest(tmp_path: Path) -> None:
    body = (
        _client(tmp_path)
        .post(
            "/api/v1/copilot/query",
            json={"question": "How accurate is the youth population forecast?"},
        )
        .json()
    )

    assert body["status"] == "answered"
    assert body["answer"].startswith("Model cohort-change-ratio-v1 was selected")
    assert "contained 86% of 200 past outcomes" in body["answer"]
