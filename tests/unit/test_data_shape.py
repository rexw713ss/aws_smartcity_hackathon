"""Result-set profiling that decides whether a chart can be drawn honestly.

Doc 30, stage 1.
"""

import pytest

from youth_compass.agent.contracts import ObservationPoint, ObservationSeries
from youth_compass.agent.data_shape import (
    Direction,
    Granularity,
    IssueCode,
    profile_series,
)
from youth_compass.domain.types import WarningSeverity


def _series(
    points: tuple[ObservationPoint, ...],
    *,
    metric_code: str = "population_count",
    unit_code: str = "persons",
) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code=metric_code,
        unit_code=unit_code,
        population_scope="youth_specific",
        points=points,
    )


def _point(
    entity_id: str, period: str, value: float, *, estimated: float = 0.0
) -> ObservationPoint:
    return ObservationPoint(
        entity_id=entity_id,
        entity_name=entity_id.title(),
        period=period,
        value=value,
        estimated_value=estimated,
    )


def _trend(entity_id: str, values: dict[str, float]) -> tuple[ObservationPoint, ...]:
    return tuple(_point(entity_id, period, value) for period, value in values.items())


def test_an_empty_series_profiles_without_inventing_a_shape() -> None:
    profile = profile_series(_series(()))

    assert profile.entity_count == 0
    assert profile.period_count == 0
    assert profile.value_median is None
    assert profile.signals == ()
    assert profile.issues == ()
    assert not profile.is_flat


def test_structure_counts_the_grid_the_points_actually_fill() -> None:
    profile = profile_series(
        _series(
            (
                *_trend("banqiao", {"2022": 100.0, "2023": 110.0}),
                *_trend("xindian", {"2022": 40.0, "2023": 44.0}),
            )
        )
    )

    assert profile.entity_count == 2
    assert profile.period_count == 2
    assert profile.periods == ("2022", "2023")
    assert profile.granularity is Granularity.YEAR
    assert profile.coverage_ratio == 1.0


def test_granularity_distinguishes_years_months_and_a_mixed_result() -> None:
    months = profile_series(_series(_trend("banqiao", {"2023-01": 1.0, "2023-02": 2.0})))
    mixed = profile_series(_series(_trend("banqiao", {"2023": 1.0, "2023-02": 2.0})))

    assert months.granularity is Granularity.MONTH
    assert mixed.granularity is Granularity.MIXED


def test_monthly_profile_counts_absent_calendar_periods_and_recommends_a_cadence() -> None:
    profile = profile_series(
        _series(
            _trend(
                "banqiao",
                {
                    "2023-01": 1.0,
                    "2023-02": 2.0,
                    "2023-04": 4.0,
                    "2023-05": 5.0,
                    "2023-06": 6.0,
                },
            )
        )
    )

    assert profile.expected_monthly_points == 6
    assert profile.missing_monthly_points == 1
    assert profile.monthly_coverage_ratio == pytest.approx(5 / 6)
    assert profile.plot_interval_months == 3


def test_complete_long_monthly_profile_uses_quarters_to_stay_within_chart_budget() -> None:
    profile = profile_series(
        _series(
            tuple(
                _point("banqiao", f"{year:04d}-{month:02d}", float(year * 100 + month))
                for year in range(2018, 2024)
                for month in range(1, 13)
            )
        )
    )

    assert profile.missing_monthly_points == 0
    assert profile.monthly_coverage_ratio == 1.0
    assert profile.plot_interval_months == 3


def test_a_missing_year_in_a_long_series_uses_two_year_blocks() -> None:
    profile = profile_series(
        _series(
            tuple(
                _point("banqiao", f"{year:04d}-{month:02d}", float(year * 100 + month))
                for year in range(2011, 2027)
                if year != 2017
                for month in range(1, 13)
            )
        )
    )

    assert profile.missing_monthly_points == 12
    assert profile.plot_interval_months == 24


def test_a_signal_reports_movement_against_the_series_own_volatility() -> None:
    profile = profile_series(
        _series(_trend("banqiao", {"2020": 100.0, "2021": 90.0, "2022": 80.0, "2023": 70.0}))
    )
    signal = profile.signals[0]

    assert signal.direction is Direction.DECREASED
    assert signal.first_value == 100.0
    assert signal.last_value == 70.0
    assert signal.net_change == -30.0
    assert signal.net_change_ratio is not None
    assert round(signal.net_change_ratio, 3) == -0.3
    # Every step is identical, so there is no noise to divide by; the module
    # reports that instead of dividing by zero or substituting a value.
    assert signal.signal_to_noise is None


def test_a_ratio_against_a_zero_baseline_is_reported_as_unknown() -> None:
    profile = profile_series(_series(_trend("banqiao", {"2022": 0.0, "2023": 50.0})))

    assert profile.signals[0].net_change_ratio is None
    assert profile.signals[0].direction is Direction.INCREASED


def test_a_noisy_series_that_ends_where_it_started_scores_low_signal() -> None:
    profile = profile_series(
        _series(_trend("banqiao", {"2020": 100.0, "2021": 130.0, "2022": 70.0, "2023": 100.0}))
    )
    signal = profile.signals[0]

    assert signal.direction is Direction.UNCHANGED
    assert signal.signal_to_noise == 0.0


def test_a_series_that_barely_moves_is_flat() -> None:
    profile = profile_series(
        _series(
            (
                *_trend("banqiao", {"2022": 1000.0, "2023": 1005.0}),
                *_trend("xindian", {"2022": 800.0, "2023": 803.0}),
            )
        )
    )

    assert profile.is_flat


def test_a_series_with_one_real_mover_is_not_flat() -> None:
    profile = profile_series(
        _series(
            (
                *_trend("banqiao", {"2022": 1000.0, "2023": 1005.0}),
                *_trend("xindian", {"2022": 800.0, "2023": 600.0}),
            )
        )
    )

    assert not profile.is_flat


def test_dispersion_compares_entities_inside_one_period() -> None:
    profile = profile_series(
        _series(
            (
                *_trend("banqiao", {"2022": 500.0, "2023": 1000.0}),
                *_trend("pinglin", {"2022": 5.0, "2023": 10.0}),
            )
        )
    )

    assert profile.comparison_period == "2023"
    assert profile.spread_ratio == 100.0
    assert profile.coefficient_of_variation is not None


def test_dispersion_falls_back_to_the_newest_period_two_entities_share() -> None:
    profile = profile_series(
        _series(
            (
                *_trend("banqiao", {"2022": 500.0, "2023": 520.0, "2024": 530.0}),
                *_trend("xindian", {"2022": 100.0, "2023": 104.0}),
            )
        )
    )

    assert profile.comparison_period == "2023"


def test_a_single_entity_has_no_cross_entity_dispersion() -> None:
    profile = profile_series(_series(_trend("banqiao", {"2022": 500.0, "2023": 520.0})))

    assert profile.comparison_period is None
    assert profile.spread_ratio is None


def test_conflicting_values_for_one_entity_period_are_an_error() -> None:
    profile = profile_series(
        _series((_point("banqiao", "2023", 100.0), _point("banqiao", "2023", 120.0)))
    )
    issue = profile.issue(IssueCode.DUPLICATE_OBSERVATION)

    assert issue is not None
    assert issue.severity is WarningSeverity.ERROR
    assert issue.entity_ids == ("banqiao",)
    assert issue.periods == ("2023",)
    assert profile.has_blocking_issue


def test_a_negative_count_is_an_error_on_a_count_metric() -> None:
    profile = profile_series(_series(_trend("banqiao", {"2022": 100.0, "2023": -5.0})))
    issue = profile.issue(IssueCode.NEGATIVE_COUNT)

    assert issue is not None
    assert issue.severity is WarningSeverity.ERROR
    assert issue.entity_ids == ("banqiao",)


def test_a_negative_value_on_a_non_count_metric_is_not_flagged() -> None:
    profile = profile_series(
        _series(
            _trend("banqiao", {"2022": 1.0, "2023": -5.0}),
            metric_code="net_migration_rate",
            unit_code="rate",
        )
    )

    assert profile.issue(IssueCode.NEGATIVE_COUNT) is None


def test_a_still_collecting_final_period_is_flagged_before_a_line_plots_its_cliff() -> None:
    points = tuple(
        _point(f"district_{index}", "2023", 100.0 + index) for index in range(5)
    ) + tuple(_point(f"district_{index}", "2024", 101.0 + index) for index in range(2))
    profile = profile_series(_series(points))
    issue = profile.issue(IssueCode.PARTIAL_LATEST_PERIOD)

    assert issue is not None
    assert issue.periods == ("2024",)
    assert issue.severity is WarningSeverity.WARNING


def test_a_complete_final_period_is_not_flagged() -> None:
    points = tuple(
        _point(f"district_{index}", period, 100.0 + index)
        for index in range(5)
        for period in ("2023", "2024")
    )

    assert profile_series(_series(points)).issue(IssueCode.PARTIAL_LATEST_PERIOD) is None


def test_a_jump_outside_the_usual_step_size_is_reported_as_a_level_shift() -> None:
    profile = profile_series(
        _series(
            _trend(
                "banqiao",
                {"2019": 100.0, "2020": 102.0, "2021": 101.0, "2022": 400.0, "2023": 402.0},
            )
        )
    )
    issue = profile.issue(IssueCode.LEVEL_SHIFT)

    assert issue is not None
    assert issue.entity_ids == ("banqiao",)
    assert issue.periods == ("2022",)


def test_a_steadily_growing_series_is_not_a_level_shift() -> None:
    profile = profile_series(
        _series(
            _trend(
                "banqiao",
                {"2019": 100.0, "2020": 110.0, "2021": 121.0, "2022": 133.0, "2023": 146.0},
            )
        )
    )

    assert profile.issue(IssueCode.LEVEL_SHIFT) is None


def test_a_half_empty_grid_is_reported_as_sparse() -> None:
    points = (
        *_trend("banqiao", {"2020": 1.0, "2021": 2.0}),
        *_trend("xindian", {"2022": 3.0}),
        *_trend("sanchong", {"2023": 4.0}),
    )
    profile = profile_series(_series(points))
    issue = profile.issue(IssueCode.SPARSE_COVERAGE)

    assert issue is not None
    assert profile.coverage_ratio < 0.7


def test_the_estimated_share_and_unmapped_entities_are_exposed_not_narrated() -> None:
    profile = profile_series(
        _series(
            (
                _point("banqiao", "2022", 100.0, estimated=10.0),
                _point("banqiao", "2023", 110.0),
                _point("somewhere_else", "2022", 5.0),
                _point("somewhere_else", "2023", 6.0),
            )
        )
    )

    assert profile.estimated_point_ratio == 0.25
    assert profile.unmapped_entity_ids == ("somewhere_else",)
    # Freshness, coverage, and the estimated-value caveat remain owned by
    # limitations.py; this module only supplies the inputs.
    assert all(issue.code is not IssueCode.SPARSE_COVERAGE for issue in profile.issues)
