"""Backtest summaries, the acceptance gate, and empirical intervals."""

import pytest

from youth_compass.forecasting.evaluation import (
    BacktestRecord,
    HorizonAccuracy,
    SizeClass,
    interval_widths,
    quantile,
    rolling_coverage,
    run_backtest,
    select_model,
    size_class,
    summarize,
)


def _record(
    predicted: float,
    actual: float = 100.0,
    *,
    model: str = "m",
    horizon: int = 1,
    origin: int = 2020,
    klass: SizeClass = SizeClass.STANDARD,
) -> BacktestRecord:
    return BacktestRecord(
        model=model,
        district_code="01",
        origin_year=origin,
        horizon=horizon,
        predicted=predicted,
        actual=actual,
        size_class=klass,
    )


def _accuracy(*mapes: float) -> tuple[HorizonAccuracy, ...]:
    return tuple(
        HorizonAccuracy(horizon=h, samples=10, mape_percent=m, p90_ape_percent=m, bias_percent=0)
        for h, m in enumerate(mapes, start=1)
    )


def test_size_class_follows_the_small_area_threshold() -> None:
    assert size_class(9_999) is SizeClass.SMALL
    assert size_class(10_000) is SizeClass.STANDARD


def test_run_backtest_only_scores_observed_outcomes() -> None:
    observed = {(2021, "01"): 110.0}

    records = run_backtest(
        {"flat": lambda origin, district, horizon: 100.0},
        lambda year, district: observed.get((year, district)),
        districts=["01"],
        origins=[2020],
        horizons=[1, 2],
        size_classes={"01": SizeClass.STANDARD},
    )

    assert [(record.horizon, record.actual) for record in records] == [(1, 110.0)]


def test_summarize_reports_percent_error_and_bias() -> None:
    records = [_record(110.0), _record(95.0)]

    (summary,) = summarize(records, "m")

    assert summary.samples == 2
    assert summary.mape_percent == pytest.approx(7.5)
    assert summary.bias_percent == pytest.approx(2.5)


def test_the_gate_selects_the_best_model_that_beats_the_baseline_everywhere() -> None:
    gate = select_model(
        {
            "naive": _accuracy(2.0, 4.0),
            "trend": _accuracy(1.0, 5.0),
            "cohort": _accuracy(1.5, 2.5),
        },
        baseline="naive",
    )

    assert gate.selected_model == "cohort"
    assert gate.passed


def test_the_gate_fails_when_no_model_beats_the_baseline() -> None:
    gate = select_model(
        {"naive": _accuracy(1.0, 2.0), "cohort": _accuracy(1.0, 3.0)},
        baseline="naive",
    )

    assert not gate.passed
    assert "does not beat naive" in gate.reasons[0]


def test_an_interval_always_contains_its_point() -> None:
    records = [_record(100.0 + offset) for offset in range(1, 21)]  # all over-forecasts

    width = interval_widths(records, "m")[(1, SizeClass.STANDARD)]
    lower, upper = width.interval(500.0)

    assert lower < 500.0 < upper


def test_the_half_width_is_the_absolute_error_quantile() -> None:
    # Errors of -10% .. +10%: both tails inform one symmetric width.
    records = [_record(100.0 + offset) for offset in range(-10, 11)]

    width = interval_widths(records, "m", error_quantile=0.9)[(1, SizeClass.STANDARD)]

    assert width.absolute_error == pytest.approx(0.09)
    assert width.interval(100.0) == pytest.approx((100 / 1.09, 100 / 0.91))


def test_a_small_class_with_few_errors_borrows_the_pooled_errors() -> None:
    records = [_record(100.0 + offset) for offset in range(20)]
    records.append(_record(150.0, klass=SizeClass.SMALL))

    widths = interval_widths(records, "m")

    assert widths[(1, SizeClass.SMALL)].pooled
    assert widths[(1, SizeClass.SMALL)].samples == 21
    assert not widths[(1, SizeClass.STANDARD)].pooled


def test_rolling_coverage_uses_only_errors_observable_at_the_origin() -> None:
    # Early origins err by 1%; the 2030 origin errs by 50%. An interval for the
    # 2030 forecast may learn only from outcomes up to 2030, so it misses.
    early = [_record(101.0, origin=2000 + index) for index in range(20)]
    late = _record(150.0, origin=2030)
    # This record's outcome (2036) was not known in 2030 and must not widen it.
    future = _record(200.0, origin=2035)

    report = rolling_coverage([*early, late, future], "m")

    assert report is not None
    assert report.samples == 12  # origins 2010-2019, 2030, 2035 have >= 10 known errors
    assert report.by_horizon[1] == (10 / 12, 12)


def test_rolling_coverage_is_none_without_enough_history() -> None:
    assert rolling_coverage([_record(101.0, origin=2020)], "m") is None


def test_quantile_interpolates_linearly() -> None:
    assert quantile([0.0, 10.0], 0.9) == pytest.approx(9.0)
    assert quantile([3.0, 1.0, 2.0], 0.5) == 2.0
