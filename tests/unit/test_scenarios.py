import csv
from pathlib import Path

import pytest

from youth_compass.decisioning import (
    PopulationBalanceMode,
    ScenarioAdjustment,
    ScenarioOperation,
    YouthPopulationScenarioService,
)
from youth_compass.domain import QueryNotPermittedError


def _write_population(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "民國年",
                "月",
                "區代碼",
                "行政區",
                "年齡標籤",
                "年齡下限",
                "年齡上限",
                "青年關係",
                "青年權重",
                "性別",
                "人數",
            ]
        )
        for code in range(1, 30):
            for age in range(0, 36):
                value = code * 100 if age == 18 else code * 10 if age == 35 else 0
                writer.writerow(
                    [
                        115,
                        7,
                        code,
                        f"district-{code}",
                        f"{age}歲",
                        age,
                        age,
                        "完全落入",
                        1,
                        "總計",
                        value,
                    ]
                )


def _write_population_history(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "民國年",
                "月",
                "區代碼",
                "行政區",
                "年齡標籤",
                "年齡下限",
                "年齡上限",
                "青年關係",
                "青年權重",
                "性別",
                "人數",
            ]
        )
        for code in range(1, 30):
            if code == 17:
                values = (1_000, 900, 810, 729)
            elif code >= 22:
                values = (1_000, 1_100, 1_210, 1_331)
            else:
                values = (1_000, 1_000, 1_000, 1_000)
            for year, value in zip(range(112, 116), values, strict=True):
                for age in range(0, 36):
                    writer.writerow(
                        [
                            year,
                            7,
                            code,
                            f"district-{code}",
                            f"{age}歲",
                            age,
                            age,
                            "完全落入",
                            1,
                            "總計",
                            value,
                        ]
                    )


def test_open_scenario_discloses_assumption_and_changes_total(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    service = YouthPopulationScenarioService(source)

    result = service.run(
        (
            ScenarioAdjustment(
                district_id="Linkou",
                operation=ScenarioOperation.ABSOLUTE_CHANGE,
                value=2_000,
            ),
        ),
        balance_mode=PopulationBalanceMode.OPEN,
    )

    linkou = next(row for row in result.rows if row.district_code == "17")
    assert result.observed_period == "2026-07"
    assert linkou.baseline_value == 1_870
    assert linkou.scenario_value == 3_870
    assert result.total_delta == 2_000
    assert not result.population_conserved
    assert {item.kind.value for item in result.evidence} == {
        "official",
        "derived",
        "user_assumption",
    }


def test_redistribution_preserves_exact_integer_total(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    service = YouthPopulationScenarioService(source)

    result = service.run(
        (
            ScenarioAdjustment(
                district_id="17",
                operation=ScenarioOperation.PERCENT_CHANGE,
                value=10,
            ),
        ),
        balance_mode=PopulationBalanceMode.REDISTRIBUTE,
    )

    linkou = next(row for row in result.rows if row.district_code == "17")
    assert linkou.absolute_delta == 187
    assert result.baseline_total == result.scenario_total
    assert result.population_conserved
    assert sum(row.absolute_delta for row in result.rows) == 0


def test_transfer_cannot_exceed_source_population(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    service = YouthPopulationScenarioService(source)

    with pytest.raises(QueryNotPermittedError, match="exceeds"):
        service.run(
            (
                ScenarioAdjustment(
                    district_id="Linkou",
                    source_district_id="Wulai",
                    operation=ScenarioOperation.TRANSFER,
                    value=4_000,
                ),
            ),
            balance_mode=PopulationBalanceMode.OPEN,
        )


def test_multiple_adjustments_execute_in_order(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    _write_population(source)
    service = YouthPopulationScenarioService(source)

    result = service.run(
        (
            ScenarioAdjustment(
                district_id="Linkou",
                operation=ScenarioOperation.ABSOLUTE_CHANGE,
                value=1_000,
            ),
            ScenarioAdjustment(
                district_id="Linkou",
                operation=ScenarioOperation.PERCENT_CHANGE,
                value=10,
            ),
            ScenarioAdjustment(
                district_id="Linkou",
                source_district_id="Banqiao",
                operation=ScenarioOperation.TRANSFER,
                value=50,
            ),
        ),
        balance_mode=PopulationBalanceMode.OPEN,
    )

    linkou = next(row for row in result.rows if row.district_code == "17")
    banqiao = next(row for row in result.rows if row.district_code == "01")
    # Linkou starts at 1,870: +1,000, then +10% of 2,870, then +50 transfer.
    assert linkou.scenario_value == 3_207
    assert banqiao.absolute_delta == -50
    assert result.total_delta == 1_287
    assert len(result.assumptions) == 3


def test_projection_uses_historical_cohorts_and_a_data_derived_benchmark(
    tmp_path: Path,
) -> None:
    source = tmp_path / "population.csv"
    _write_population_history(source)
    service = YouthPopulationScenarioService(source)

    result = service.run(
        (
            ScenarioAdjustment(
                district_id="Linkou",
                operation=ScenarioOperation.MATCH_TOP_QUARTILE_RETENTION,
            ),
        ),
        balance_mode=PopulationBalanceMode.OPEN,
        target_year=2030,
    )

    linkou = next(row for row in result.rows if row.district_code == "17")
    assert result.target_year == 2030
    assert linkou.historical_retention_rate == pytest.approx(0.9)
    assert linkou.scenario_retention_rate == pytest.approx(1.1)
    assert linkou.baseline_value == round(18 * 729 * 0.9**4)
    assert linkou.scenario_value == round(18 * 729 * 1.1**4)
    assert len(result.trajectory) == 5
    assert result.trajectory[-1].baseline_value == result.baseline_total
    assert result.trajectory[-1].scenario_value == result.scenario_total
    assert any(item.kind.value == "derived" for item in result.evidence)
    assert len(linkou.trajectory) == 5
    assert linkou.trajectory[-1].baseline_value == linkou.baseline_value
    assert linkou.trajectory[-1].scenario_value == linkou.scenario_value
    assert linkou.trajectory[-1].baseline_value < result.baseline_total


def test_impact_chart_follows_the_district_and_sizes_the_shock(tmp_path: Path) -> None:
    from youth_compass.agent.impact import _impact_visualizations

    source = tmp_path / "population.csv"
    _write_population_history(source)
    result = YouthPopulationScenarioService(source).run(
        (
            ScenarioAdjustment(
                district_id="Linkou", operation=ScenarioOperation.ABSOLUTE_CHANGE, value=2_000
            ),
        ),
        balance_mode=PopulationBalanceMode.OPEN,
        target_year=2030,
    )
    linkou = next(row for row in result.rows if row.district_code == "17")

    (chart,) = _impact_visualizations(result, linkou, "If 2,000 young people move to Linkou?")

    baseline = [row for row in chart.rows if row["path"] == "Baseline"]
    scenario = [row for row in chart.rows if row["path"] == "Scenario"]
    assert baseline[-1]["population"] == linkou.baseline_value
    # A one-off shock leaves the baseline only in the final year.
    assert [row["year"] for row in scenario] == [2029, 2030]
    assert chart.reference_lines[0].value == linkou.trajectory[0].baseline_value
    assert chart.headline is not None
    assert chart.headline.startswith("+2,000 people is ")
