"""Cohort change ratios: estimation, projection, and the exact decomposition."""

import pytest

from youth_compass.forecasting.cohort import (
    CohortInputError,
    estimate_change_ratios,
    project_youth,
    youth_count,
)


def _ages(value: float) -> dict[int, float]:
    return {age: value for age in range(0, 41)}


def _snapshots(
    years: range, per_age: dict[str, float], ratio: float = 1.0
) -> dict[int, dict[str, dict[int, float]]]:
    """Each age is ``ratio`` times the previous year's count one age younger."""

    snapshots: dict[int, dict[str, dict[int, float]]] = {}
    for offset, year in enumerate(years):
        snapshots[year] = {
            code: {age: value * ratio ** min(offset, age) for age in range(0, 41)}
            for code, value in per_age.items()
        }
    return snapshots


class TestEstimateChangeRatios:
    def test_recovers_a_constant_ratio(self) -> None:
        snapshots = _snapshots(range(2015, 2021), {"01": 100.0, "02": 50.0}, ratio=0.9)

        ratios = estimate_change_ratios(snapshots, 2020, window_years=5)

        assert ratios["01"][20] == pytest.approx(0.9)
        assert ratios["02"][0] == pytest.approx(0.9)

    def test_ignores_years_after_the_origin(self) -> None:
        snapshots = _snapshots(range(2015, 2021), {"01": 100.0}, ratio=1.0)
        # A shock after the origin must not leak into the ratios a backtest uses.
        snapshots[2021] = {"01": {age: 1.0 for age in range(0, 41)}}

        ratios = estimate_change_ratios(snapshots, 2020, window_years=5)

        assert ratios["01"][25] == pytest.approx(1.0)

    def test_uses_the_median_so_one_abnormal_year_does_not_dominate(self) -> None:
        snapshots = {year: {"01": _ages(100.0)} for year in range(2015, 2021)}
        snapshots[2018] = {"01": _ages(150.0)}  # 2017->2018 is 1.5, 2018->2019 is 0.67

        ratios = estimate_change_ratios(snapshots, 2020, window_years=5)

        assert ratios["01"][10] == pytest.approx(1.0)

    def test_skips_pairs_across_a_missing_year(self) -> None:
        snapshots = _snapshots(range(2011, 2021), {"01": 100.0}, ratio=1.0)
        del snapshots[2017]

        ratios = estimate_change_ratios(snapshots, 2020, window_years=5)

        assert ratios["01"][5] == pytest.approx(1.0)

    def test_a_district_age_with_no_count_takes_the_city_ratio(self) -> None:
        snapshots = _snapshots(range(2016, 2021), {"01": 100.0, "02": 100.0}, ratio=0.8)
        for year in snapshots:
            snapshots[year]["02"][7] = 0.0

        ratios = estimate_change_ratios(snapshots, 2020, window_years=4)

        assert ratios["02"][7] == pytest.approx(ratios["01"][7])

    def test_rejects_a_window_without_consecutive_years(self) -> None:
        snapshots = {2015: {"01": _ages(1.0)}, 2020: {"01": _ages(1.0)}}

        with pytest.raises(CohortInputError):
            estimate_change_ratios(snapshots, 2020, window_years=3)


class TestProjectYouth:
    def test_a_ratio_of_one_moves_cohorts_without_change(self) -> None:
        base = {age: float(age) for age in range(0, 41)}
        ratios = {age: 1.0 for age in range(0, 35)}

        projection = project_youth("01", base, ratios, origin_year=2026, horizon=5)

        assert projection.value == pytest.approx(sum(range(13, 31)))
        assert projection.net_change == pytest.approx(0.0)
        assert projection.year == 2031

    def test_components_add_up_to_the_projection(self) -> None:
        base = {age: 100.0 + age for age in range(0, 41)}
        ratios = {age: 0.97 for age in range(0, 35)}

        projection = project_youth("01", base, ratios, origin_year=2026, horizon=3)

        assert projection.base_value == youth_count(base)
        assert projection.entering == pytest.approx(sum(100.0 + age for age in (15, 16, 17)))
        assert projection.ageing_out == pytest.approx(sum(100.0 + age for age in (33, 34, 35)))
        assert projection.value == pytest.approx(
            projection.base_value
            + projection.entering
            - projection.ageing_out
            + projection.net_change
        )
        assert projection.value == pytest.approx(
            sum((100.0 + age) * 0.97**3 for age in range(15, 33))
        )

    @pytest.mark.parametrize("horizon", [0, 18])
    def test_rejects_a_horizon_that_needs_unborn_cohorts(self, horizon: int) -> None:
        with pytest.raises(CohortInputError):
            project_youth(
                "01", _ages(1.0), {age: 1.0 for age in range(35)}, origin_year=2026, horizon=horizon
            )
