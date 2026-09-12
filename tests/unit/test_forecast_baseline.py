"""The baseline forecast: log-linear trend with widening uncertainty bands."""

import pytest

from youth_compass.forecasting import ForecastInputError, forecast_series


class TestForecastSeries:
    def test_projects_a_clean_growth_trend_forward(self) -> None:
        # 10% annual growth: 100, 110, 121 -> next should be ~133.1.
        points = forecast_series(
            {"banqiao": [(2023, 100.0), (2024, 110.0), (2025, 121.0)]},
            horizon_years=2,
        )

        years = [p.year_gregorian for p in points]
        assert years == [2026, 2027]
        assert points[0].value == pytest.approx(133.1, rel=0.01)
        assert points[1].value == pytest.approx(146.41, rel=0.01)

    def test_every_interval_contains_its_point(self) -> None:
        points = forecast_series(
            {"a": [(2023, 100.0), (2024, 118.0), (2025, 121.0)]},
            horizon_years=3,
        )

        for point in points:
            assert point.lower <= point.value <= point.upper

    def test_bands_widen_with_the_horizon(self) -> None:
        # A noisy history (not perfectly log-linear) yields non-zero residuals,
        # so later years must carry wider intervals than earlier ones.
        points = forecast_series(
            {"a": [(2020, 100.0), (2021, 130.0), (2022, 150.0), (2023, 210.0)]},
            horizon_years=3,
        )
        widths = [point.upper - point.lower for point in points]

        assert widths[0] < widths[1] < widths[2]

    def test_districts_are_forecast_independently_and_sorted(self) -> None:
        points = forecast_series(
            {
                "zzz": [(2024, 50.0), (2025, 55.0)],
                "aaa": [(2024, 200.0), (2025, 210.0)],
            },
            horizon_years=1,
        )

        assert [p.district_code for p in points] == ["aaa", "zzz"]

    def test_all_series_share_the_latest_base_year(self) -> None:
        # One district's history ends earlier; the horizon still starts from the
        # global latest year so the artifact has aligned forecast years.
        points = forecast_series(
            {
                "current": [(2024, 100.0), (2025, 110.0)],
                "stale": [(2022, 40.0), (2023, 44.0)],
            },
            horizon_years=1,
        )

        assert {p.year_gregorian for p in points} == {2026}

    def test_a_district_with_one_point_is_skipped(self) -> None:
        points = forecast_series(
            {
                "ok": [(2024, 100.0), (2025, 110.0)],
                "single": [(2025, 500.0)],
            },
            horizon_years=1,
        )

        assert {p.district_code for p in points} == {"ok"}

    def test_no_forecastable_series_raises(self) -> None:
        with pytest.raises(ForecastInputError, match="two or more"):
            forecast_series({"single": [(2025, 100.0)]}, horizon_years=1)

    def test_non_positive_values_are_dropped(self) -> None:
        # Log-linear needs positive values; a zero/negative point is ignored,
        # leaving too few to forecast here.
        with pytest.raises(ForecastInputError):
            forecast_series({"a": [(2024, 0.0), (2025, 100.0)]}, horizon_years=1)

    def test_zero_horizon_is_rejected(self) -> None:
        with pytest.raises(ForecastInputError, match="horizon"):
            forecast_series({"a": [(2024, 1.0), (2025, 2.0)]}, horizon_years=0)

    def test_flat_history_forecasts_flat(self) -> None:
        points = forecast_series(
            {"a": [(2023, 100.0), (2024, 100.0), (2025, 100.0)]},
            horizon_years=1,
        )

        assert points[0].value == pytest.approx(100.0, rel=1e-6)
        # A perfectly flat fit still carries the minimum relative band.
        assert points[0].upper > points[0].value
