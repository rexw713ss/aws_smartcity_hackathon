"""Temporal backtest, acceptance gate, and empirical intervals for annual forecasts.

Pure and IO-free. Every candidate is re-run from past origins with only the data
available at that origin, and its predictions are compared with what was later
observed (Williams & Goodman 1971). The same errors decide whether a forecast may
be published and how wide its interval is, so the reported uncertainty is what
the model has actually missed by, not a distributional assumption.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

# Wilson et al. (2021): small-area forecast errors rise rapidly below this size.
SMALL_AREA_POPULATION = 10_000
# Intervals aim to contain this share of outcomes, measured in pseudo-real time.
TARGET_COVERAGE = 0.8
# Half-width is this quantile of past absolute errors. Separate lower and upper
# quantiles covered only 64% of outcomes in pseudo-real time, because each tail
# is estimated from a handful of correlated district errors; one absolute
# quantile uses both tails' evidence. See docs/31, "Interval calibration".
ERROR_QUANTILE = 0.9
# A size class with fewer errors than this borrows the pooled horizon errors.
MIN_CLASS_SAMPLES = 10

# (origin_year, district_code, horizon) -> predicted value, or None when the
# model cannot predict from that origin.
Predictor = Callable[[int, str, int], float | None]
# (year, district_code) -> observed value, or None when not observed.
Observed = Callable[[int, str], float | None]


class SizeClass(StrEnum):
    SMALL = "small"
    STANDARD = "standard"


def size_class(total_population: float) -> SizeClass:
    return SizeClass.SMALL if total_population < SMALL_AREA_POPULATION else SizeClass.STANDARD


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    model: str
    district_code: str
    origin_year: int
    horizon: int
    predicted: float
    actual: float
    size_class: SizeClass

    @property
    def signed_error(self) -> float:
        """(predicted - actual) / actual; positive means the forecast was too high."""

        return (self.predicted - self.actual) / self.actual


@dataclass(frozen=True, slots=True)
class HorizonAccuracy:
    horizon: int
    samples: int
    mape_percent: float
    p90_ape_percent: float
    bias_percent: float


@dataclass(frozen=True, slots=True)
class GateResult:
    selected_model: str | None
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.selected_model is not None


@dataclass(frozen=True, slots=True)
class IntervalWidth:
    """Relative half-width of an interval, from one horizon and size class of errors."""

    horizon: int
    size_class: SizeClass
    samples: int
    absolute_error: float
    pooled: bool

    def interval(self, value: float) -> tuple[float, float]:
        """Bounds for the actual value given a prediction; they always contain it.

        With e = (predicted - actual) / actual and |e| <= a, the actual lies in
        [predicted / (1 + a), predicted / (1 - a)].
        """

        width = min(max(self.absolute_error, 0.0), 0.99)
        return value / (1.0 + width), value / (1.0 - width)


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Share of outcomes inside intervals built only from errors known at the time."""

    coverage: float
    samples: int
    by_horizon: dict[int, tuple[float, int]]
    by_size_class: dict[SizeClass, tuple[float, int]]


def run_backtest(
    models: Mapping[str, Predictor],
    observed: Observed,
    *,
    districts: Sequence[str],
    origins: Iterable[int],
    horizons: Iterable[int],
    size_classes: Mapping[str, SizeClass],
) -> list[BacktestRecord]:
    """Predict from every origin and horizon that has an observed outcome."""

    records: list[BacktestRecord] = []
    horizon_list = list(horizons)
    for origin in origins:
        for horizon in horizon_list:
            for district in districts:
                actual = observed(origin + horizon, district)
                if actual is None or actual <= 0:
                    continue
                for name, predict in models.items():
                    predicted = predict(origin, district, horizon)
                    if predicted is None or not math.isfinite(predicted):
                        continue
                    records.append(
                        BacktestRecord(
                            model=name,
                            district_code=district,
                            origin_year=origin,
                            horizon=horizon,
                            predicted=predicted,
                            actual=actual,
                            size_class=size_classes[district],
                        )
                    )
    return records


def summarize(records: Iterable[BacktestRecord], model: str) -> tuple[HorizonAccuracy, ...]:
    """Accuracy per horizon for one model."""

    by_horizon: dict[int, list[float]] = {}
    for record in records:
        if record.model == model:
            by_horizon.setdefault(record.horizon, []).append(record.signed_error)
    summaries: list[HorizonAccuracy] = []
    for horizon in sorted(by_horizon):
        errors = by_horizon[horizon]
        absolute = [abs(error) for error in errors]
        summaries.append(
            HorizonAccuracy(
                horizon=horizon,
                samples=len(errors),
                mape_percent=100 * sum(absolute) / len(absolute),
                p90_ape_percent=100 * quantile(absolute, 0.9),
                bias_percent=100 * sum(errors) / len(errors),
            )
        )
    return tuple(summaries)


def select_model(
    accuracy: Mapping[str, Sequence[HorizonAccuracy]],
    *,
    baseline: str,
) -> GateResult:
    """Pick the lowest mean-MAPE candidate that beats ``baseline`` at every horizon."""

    if baseline not in accuracy or not accuracy[baseline]:
        return GateResult(None, (f"baseline {baseline!r} has no backtest results",))
    reference = {item.horizon: item.mape_percent for item in accuracy[baseline]}
    reasons: list[str] = []
    eligible: list[tuple[float, str]] = []
    for name in sorted(accuracy):
        if name == baseline:
            continue
        results = {item.horizon: item.mape_percent for item in accuracy[name]}
        missing = sorted(set(reference) - set(results))
        if missing:
            reasons.append(f"{name} has no backtest results for horizons {missing}")
            continue
        losing = sorted(h for h in reference if results[h] >= reference[h])
        if losing:
            reasons.append(f"{name} does not beat {baseline} at horizons {losing}")
            continue
        eligible.append((sum(results.values()) / len(results), name))
    if not eligible:
        return GateResult(None, tuple(reasons) or ("no candidate besides the baseline",))
    selected = min(eligible)[1]
    return GateResult(selected, (f"{selected} has the lowest mean MAPE and beats {baseline}",))


def interval_widths(
    records: Iterable[BacktestRecord],
    model: str,
    *,
    error_quantile: float = ERROR_QUANTILE,
) -> dict[tuple[int, SizeClass], IntervalWidth]:
    """Absolute-error quantile per horizon and size class for one model."""

    selected = [record for record in records if record.model == model]
    horizons = sorted({record.horizon for record in selected})
    return {
        (horizon, klass): _width(selected, horizon, klass, error_quantile)
        for horizon in horizons
        for klass in SizeClass
    }


def rolling_coverage(
    records: Sequence[BacktestRecord],
    model: str,
    *,
    error_quantile: float = ERROR_QUANTILE,
) -> CoverageReport | None:
    """Coverage in pseudo-real time: each interval uses only errors already observable.

    A forecast made at origin ``t`` can only learn from past forecasts whose
    target year is at or before ``t``. Fitting on every other origin would use
    outcomes that had not happened yet and overstate coverage.
    """

    selected = [record for record in records if record.model == model]
    inside_all = total_all = 0
    by_horizon: dict[int, list[int]] = {}
    by_class: dict[SizeClass, list[int]] = {}
    for record in selected:
        known = [
            item
            for item in selected
            if item.horizon == record.horizon
            and item.origin_year + item.horizon <= record.origin_year
        ]
        if len(known) < MIN_CLASS_SAMPLES:
            continue
        width = _width(known, record.horizon, record.size_class, error_quantile)
        lower, upper = width.interval(record.predicted)
        hit = int(lower <= record.actual <= upper)
        inside_all += hit
        total_all += 1
        for bucket in (
            by_horizon.setdefault(record.horizon, [0, 0]),
            by_class.setdefault(record.size_class, [0, 0]),
        ):
            bucket[0] += hit
            bucket[1] += 1
    if not total_all:
        return None
    return CoverageReport(
        coverage=inside_all / total_all,
        samples=total_all,
        by_horizon={key: (hit / count, count) for key, (hit, count) in sorted(by_horizon.items())},
        by_size_class={key: (hit / count, count) for key, (hit, count) in by_class.items()},
    )


def _width(
    records: Sequence[BacktestRecord],
    horizon: int,
    klass: SizeClass,
    error_quantile: float,
) -> IntervalWidth:
    pooled = [abs(record.signed_error) for record in records if record.horizon == horizon]
    own = [
        abs(record.signed_error)
        for record in records
        if record.horizon == horizon and record.size_class is klass
    ]
    use_pooled = len(own) < MIN_CLASS_SAMPLES
    source = pooled if use_pooled else own
    return IntervalWidth(
        horizon=horizon,
        size_class=klass,
        samples=len(source),
        absolute_error=quantile(source, error_quantile),
        pooled=use_pooled,
    )


def quantile(values: Sequence[float], q: float) -> float:
    """Linearly interpolated quantile, matching NumPy's default method."""

    if not values:
        raise ValueError("quantile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    below = math.floor(position)
    above = math.ceil(position)
    if below == above:
        return ordered[below]
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)
