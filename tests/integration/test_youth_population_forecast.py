"""The cohort forecast generator: backtest, gate, publication, and read-back.

Feature: youth population forecast (docs/31). A synthetic registration file in
the source layout — 29 districts, single years of age, both genders — has
shrinking birth cohorts, so the youth count falls in a way a cohort model sees
coming and a last-value baseline does not.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters.local import PrecomputedParquetForecastService
from ml.youth_population_forecast import main
from tests.support.registration_source import write_registration_source
from youth_compass.ports import ForecastRequest


@pytest.fixture
def published(tmp_path: Path) -> Path:
    source = tmp_path / "population.csv"
    write_registration_source(source, shrinking=True)
    output = tmp_path / "forecasts"
    assert main(["--source", str(source), "--output-dir", str(output)]) == 0
    return output


def test_publishes_a_cohort_forecast_with_drivers_and_evidence(published: Path) -> None:
    result = PrecomputedParquetForecastService(published / "current.parquet").get_forecast(
        ForecastRequest(metric_code="population_count", district_codes=["01"], horizon_years=5)
    )

    assert result.model_version == "cohort-change-ratio-v1"
    assert [point.year_gregorian for point in result.points] == [2024, 2025, 2026, 2027, 2028]
    evaluation = result.evaluation
    assert evaluation is not None
    assert evaluation.selected_model == "cohort-change-ratio-v1"
    assert evaluation.base_period == "2023-07"
    assert {candidate.model for candidate in evaluation.candidates} == {
        "cohort-change-ratio-v1",
        "loglinear-baseline-v1",
        "naive-last-value",
    }
    cohort = evaluation.accuracy_of("cohort-change-ratio-v1", 5)
    naive = evaluation.accuracy_of("naive-last-value", 5)
    assert cohort is not None and naive is not None
    assert cohort.mape_percent < naive.mape_percent
    for point in result.points:
        parts = point.components
        assert parts is not None
        assert point.lower <= point.value <= point.upper
        assert point.value == pytest.approx(
            parts.base_value + parts.entering - parts.ageing_out + parts.net_change
        )
        assert point.small_area is True


def test_the_model_card_records_lineage_and_parameters(published: Path) -> None:
    card = json.loads((published / "model-card.json").read_text(encoding="utf-8"))

    assert len(card["evaluation"]["source_sha256"]) == 64
    assert card["parameters"]["snapshot_month"] == 7
    assert 2017 not in card["parameters"]["snapshot_years"]
    assert card["gate"]["passed"] is True
    assert {item["size_class"] for item in card["interval_widths"]} == {"small", "standard"}
    assert card["evaluation"]["target_coverage"] == 0.8
    assert card["rolling_coverage"]["samples"] == card["evaluation"]["rolling_samples"]


def test_generated_at_round_trips_in_utc(published: Path) -> None:
    card = json.loads((published / "model-card.json").read_text(encoding="utf-8"))
    result = PrecomputedParquetForecastService(published / "current.parquet").get_forecast(
        ForecastRequest(metric_code="population_count", horizon_years=1)
    )

    assert result.generated_at == datetime.fromisoformat(card["generated_at"])
    assert result.generated_at.tzinfo == UTC


def test_a_card_from_another_run_is_not_attached(published: Path) -> None:
    card_path = published / "model-card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["generated_at"] = "2020-01-01T00:00:00+00:00"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    result = PrecomputedParquetForecastService(published / "current.parquet").get_forecast(
        ForecastRequest(metric_code="population_count", horizon_years=1)
    )

    assert result.evaluation is None
    assert result.points[0].components is not None


def test_nothing_is_published_when_no_model_beats_the_baseline(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    # A population that never changes is predicted perfectly by the last value.
    write_registration_source(source, shrinking=False)
    output = tmp_path / "forecasts"

    assert main(["--source", str(source), "--output-dir", str(output)]) == 1
    assert not (output / "current.parquet").exists()
    assert not (output / "model-card.json").exists()


def test_what_if_baseline_equals_the_published_forecast(tmp_path: Path, published: Path) -> None:
    from youth_compass.decisioning import (
        PopulationBalanceMode,
        ScenarioAdjustment,
        ScenarioOperation,
        YouthPopulationScenarioService,
    )

    source = tmp_path / "population.csv"
    forecast = PrecomputedParquetForecastService(published / "current.parquet").get_forecast(
        ForecastRequest(metric_code="population_count", horizon_years=5)
    )

    for target_year in (2024, 2028):
        scenario = YouthPopulationScenarioService(source).run(
            (
                ScenarioAdjustment(
                    district_id="01", operation=ScenarioOperation.RETENTION_RATE_CHANGE, value=1
                ),
            ),
            balance_mode=PopulationBalanceMode.OPEN,
            target_year=target_year,
        )
        published_values = {
            point.district_code: point.value
            for point in forecast.points
            if point.year_gregorian == target_year
        }
        assert {row.district_code: float(row.baseline_value) for row in scenario.rows} == (
            published_values
        )
        banqiao = next(row for row in scenario.rows if row.district_code == "01")
        assert banqiao.scenario_value > banqiao.baseline_value


def test_the_packaged_extract_reads_identically_and_serves_what_if(tmp_path: Path) -> None:
    from apps.api.dependencies import LocalRuntime
    from youth_compass.config import AppSettings
    from youth_compass.decisioning import (
        PopulationBalanceMode,
        ScenarioAdjustment,
        ScenarioOperation,
    )
    from youth_compass.forecasting.registration import (
        REGISTRATION_EXTRACT_NAME,
        load_registration_history,
        write_registration_extract,
    )

    source = tmp_path / "population.csv"
    write_registration_source(source, shrinking=True)
    data_root = tmp_path / "data"
    extract = write_registration_extract(
        source, data_root / "source" / "01_人口" / REGISTRATION_EXTRACT_NAME
    )

    assert load_registration_history(extract) == load_registration_history(source)
    assert extract.stat().st_size < source.stat().st_size / 5
    # With no CSV in the data root, as in the deployed package, What-if reads the extract.
    result = (
        LocalRuntime(data_root, settings=AppSettings(environment="local"))
        .scenarios()
        .run(
            (
                ScenarioAdjustment(
                    district_id="01", operation=ScenarioOperation.ANNUAL_NET_MIGRATION, value=10
                ),
            ),
            balance_mode=PopulationBalanceMode.OPEN,
            target_year=2025,
        )
    )
    assert result.observed_period == "2023-07"
