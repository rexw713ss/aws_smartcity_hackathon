"""The generated forecast artifact is consumable by the forecast service.

Feature: forecast artifact generator. Proves the CSV -> baseline -> Parquet
pipeline produces an artifact the PrecomputedParquetForecastService reads back,
with district codes that match what normalize_district assigns (so they align
with the curated data and the copilot).
"""

from pathlib import Path

import pytest

from adapters.local import PrecomputedParquetForecastService
from ml.forecast_baseline import main
from youth_compass.mapping.geography import normalize_district
from youth_compass.ports import ForecastRequest

_CSV = """year,district,age,population
2022,板橋區,20-24,46910
2023,板橋區,20-24,47100
2024,板橋區,20-24,47800
2025,板橋區,20-24,48200
2022,新莊區,20-24,39220
2023,新莊區,20-24,40230
2024,新莊區,20-24,41010
2025,新莊區,20-24,41720
"""


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    source = tmp_path / "history.csv"
    source.write_text(_CSV, encoding="utf-8")
    output = tmp_path / "forecasts" / "current.parquet"
    exit_code = main(["--from-csv", str(source), "--output", str(output), "--horizon-years", "3"])
    assert exit_code == 0
    return output


class TestForecastArtifactGeneration:
    def test_service_reads_the_generated_artifact(self, artifact: Path) -> None:
        banqiao = normalize_district("板橋區")
        assert banqiao is not None

        result = PrecomputedParquetForecastService(artifact).get_forecast(
            ForecastRequest(
                metric_code="population_count",
                district_codes=[banqiao.code],
                horizon_years=2,
            )
        )

        assert result.model_version == "loglinear-baseline-v1"
        assert len(result.points) == 2
        # A growing history projects upward, within its interval.
        assert result.points[0].value > 48200
        for point in result.points:
            assert point.lower <= point.value <= point.upper

    def test_district_codes_match_the_canonical_normalizer(self, artifact: Path) -> None:
        # The artifact keys on the same codes the transform assigns curated data,
        # so a forecast request by that code resolves.
        xinzhuang = normalize_district("新莊區")
        assert xinzhuang is not None

        result = PrecomputedParquetForecastService(artifact).get_forecast(
            ForecastRequest(
                metric_code="population_count",
                district_codes=[xinzhuang.code],
                horizon_years=1,
            )
        )

        assert result.points[0].district_code == xinzhuang.code

    def test_a_single_year_history_fails_cleanly(self, tmp_path: Path) -> None:
        source = tmp_path / "one.csv"
        source.write_text(
            "year,district,age,population\n2025,板橋區,20-24,48200\n", encoding="utf-8"
        )

        exit_code = main(["--from-csv", str(source), "--output", str(tmp_path / "out.parquet")])

        assert exit_code == 1  # cannot fit a trend; no artifact, non-zero exit
