"""Backtest, gate, and assemble the youth population forecast artifact and model card.

The offline CLI (`ml/youth_population_forecast.py`) and the workflow's forecast
refresh Lambda both call :func:`build`, so a forecast published by hand and one
published after an upload are produced by the same code. Writing and promoting
the files is left to each caller. See docs/31-youth-population-forecast.md.
"""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]

from youth_compass.forecasting.baseline import MODEL_VERSION as LOGLINEAR_VERSION
from youth_compass.forecasting.baseline import ForecastInputError, forecast_series
from youth_compass.forecasting.cohort import MODEL_VERSION as COHORT_VERSION
from youth_compass.forecasting.cohort import (
    ChangeRatios,
    CohortInputError,
    estimate_change_ratios,
    project_youth,
    youth_count,
)
from youth_compass.forecasting.evaluation import (
    ERROR_QUANTILE,
    TARGET_COVERAGE,
    CoverageReport,
    HorizonAccuracy,
    IntervalWidth,
    Predictor,
    SizeClass,
    interval_widths,
    rolling_coverage,
    run_backtest,
    select_model,
    size_class,
    summarize,
)
from youth_compass.forecasting.registration import (
    DISTRICT_COUNT,
    RegistrationHistory,
    RegistrationSourceError,
    load_registration_history,
)

NAIVE_VERSION = "naive-last-value"
METRIC_CODE = "population_count"
DEFAULT_HORIZON = 5
# An origin needs this many annual ratio pairs inside its window to be backtested.
MIN_ORIGIN_PAIRS = 3
# The loglinear candidate fits this many years ending at the origin.
TREND_YEARS = 5

REFERENCES = (
    "Hamilton, C. H., & Perry, J. (1962). Social Forces, 41(2), 163-170.",
    "Baker, J., Swanson, D. A., & Tayman, J. (2021). Population Research and Policy Review, "
    "40(6), 1341-1354.",
    "Williams, W. H., & Goodman, M. L. (1971). Journal of the American Statistical "
    "Association, 66(336), 752-754.",
    "Wilson, T., et al. (2021). Population Research and Policy Review, 41(3), 865-898.",
    "國家發展委員會 (2024). 中華民國人口推估(2024年至2070年).",
)
LIMITATIONS = (
    "The forecast continues recent conditions; new housing or policy can break it.",
    "Counts are registered household population (戶籍人口), not usual residents.",
    "Net change beyond ageing combines migration, mortality, and registration changes.",
    "A forecast is not causal evidence for any policy.",
)

_SCHEMA = pa.schema(
    [
        pa.field("metric_code", pa.string(), nullable=False),
        pa.field("district_code", pa.string(), nullable=False),
        pa.field("year_gregorian", pa.int32(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("lower", pa.float64(), nullable=False),
        pa.field("upper", pa.float64(), nullable=False),
        pa.field("model_version", pa.string(), nullable=False),
        pa.field("generated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("base_period", pa.string(), nullable=False),
        pa.field("base_value", pa.float64(), nullable=False),
        pa.field("entering", pa.float64(), nullable=True),
        pa.field("ageing_out", pa.float64(), nullable=True),
        pa.field("net_change", pa.float64(), nullable=True),
        pa.field("size_class", pa.string(), nullable=False),
        pa.field("total_population", pa.float64(), nullable=False),
    ]
)


class PublicationError(RuntimeError):
    """The forecast must not be published."""


def load_history(source: Path) -> RegistrationHistory:
    """Read the shared registration snapshots, as a publication failure when unusable."""

    try:
        return load_registration_history(source)
    except (RegistrationSourceError, CohortInputError) as exc:
        raise PublicationError(str(exc)) from exc


class Candidates:
    """The three backtested models, with per-origin ratio caching."""

    def __init__(self, history: RegistrationHistory, window_years: int) -> None:
        self._history = history
        self._window = window_years
        self._ratios: dict[int, ChangeRatios] = {}

    def ratios(self, origin: int) -> ChangeRatios:
        if origin not in self._ratios:
            self._ratios[origin] = estimate_change_ratios(
                self._history.snapshots, origin, window_years=self._window
            )
        return self._ratios[origin]

    def naive(self, origin: int, district: str, horizon: int) -> float | None:
        del horizon
        return self._history.youth(origin, district)

    def loglinear(self, origin: int, district: str, horizon: int) -> float | None:
        series = [
            (year, value)
            for year in range(origin - TREND_YEARS + 1, origin + 1)
            if (value := self._history.youth(year, district)) is not None
        ]
        try:
            points = forecast_series(
                {district: series}, horizon_years=horizon, last_history_year=origin
            )
        except ForecastInputError:
            return None
        return points[-1].value

    def cohort(self, origin: int, district: str, horizon: int) -> float | None:
        base = self._history.snapshots.get(origin, {}).get(district)
        if base is None:
            return None
        return project_youth(
            district, base, self.ratios(origin)[district], origin_year=origin, horizon=horizon
        ).value


def backtest_origins(history: RegistrationHistory, window_years: int) -> list[int]:
    """Origins with enough ratio pairs and at least one later observed year."""

    years = history.snapshots
    return [
        origin
        for origin in sorted(years)
        if origin < history.base_year
        and sum(
            1
            for year in range(origin - window_years, origin)
            if year in years and year + 1 in years
        )
        >= MIN_ORIGIN_PAIRS
    ]


def build(
    source: Path,
    *,
    horizon_years: int,
    window_years: int,
    generated_at: datetime,
) -> tuple[pa.Table, dict[str, object]]:
    """Run the backtest and gate, then build the artifact table and model card."""

    history = load_history(source)
    districts = history.districts
    base_year = history.base_year
    base_period = history.base_period
    classes = {code: size_class(history.totals[base_year][code]) for code in districts}
    candidates = Candidates(history, window_years)
    models = {
        NAIVE_VERSION: candidates.naive,
        LOGLINEAR_VERSION: candidates.loglinear,
        COHORT_VERSION: candidates.cohort,
    }
    origins = backtest_origins(history, window_years)
    if not origins:
        raise PublicationError("the source is too short to backtest any origin")
    records = run_backtest(
        models,
        history.youth,
        districts=districts,
        origins=origins,
        horizons=range(1, horizon_years + 1),
        size_classes=classes,
    )
    accuracy = {name: summarize(records, name) for name in models}
    covered = {item.horizon for item in accuracy[NAIVE_VERSION]}
    if covered != set(range(1, horizon_years + 1)):
        raise PublicationError(f"backtest covers horizons {sorted(covered)}, not 1-{horizon_years}")
    gate = select_model(accuracy, baseline=NAIVE_VERSION)
    if gate.selected_model is None:
        raise PublicationError("acceptance gate failed: " + "; ".join(gate.reasons))
    selected = gate.selected_model
    widths = interval_widths(records, selected)
    coverage = rolling_coverage(records, selected)

    rows = _forecast_rows(
        history,
        candidates,
        models[selected],
        selected=selected,
        widths=widths,
        classes=classes,
        horizon_years=horizon_years,
        base_period=base_period,
        generated_at=generated_at,
    )
    table = pa.Table.from_pylist(rows, schema=_SCHEMA)
    card = _model_card(
        source=source,
        history=history,
        selected=selected,
        accuracy=accuracy,
        gate_reasons=gate.reasons,
        widths=widths,
        coverage=coverage,
        origins=origins,
        base_period=base_period,
        horizon_years=horizon_years,
        window_years=window_years,
        generated_at=generated_at,
    )
    return table, card


def _forecast_rows(
    history: RegistrationHistory,
    candidates: Candidates,
    predict: Predictor,
    *,
    selected: str,
    widths: dict[tuple[int, SizeClass], IntervalWidth],
    classes: dict[str, SizeClass],
    horizon_years: int,
    base_period: str,
    generated_at: datetime,
) -> list[dict[str, object]]:
    base_year = history.base_year
    rows: list[dict[str, object]] = []
    for code in history.districts:
        base_ages = history.snapshots[base_year][code]
        base_value = youth_count(base_ages)
        for horizon in range(1, horizon_years + 1):
            entering = ageing_out = net_change = None
            if selected == COHORT_VERSION:
                projection = project_youth(
                    code,
                    base_ages,
                    candidates.ratios(base_year)[code],
                    origin_year=base_year,
                    horizon=horizon,
                )
                value = float(round(projection.value))
                entering = float(round(projection.entering))
                ageing_out = float(round(projection.ageing_out))
                # Derived after rounding so the published parts add up exactly.
                net_change = value - (base_value + entering - ageing_out)
            else:
                predicted = predict(base_year, code, horizon)
                if predicted is None:
                    raise PublicationError(f"{selected} cannot forecast district {code}")
                value = float(round(predicted))
            bounds = widths[(horizon, classes[code])]
            lower, upper = bounds.interval(value)
            rows.append(
                {
                    "metric_code": METRIC_CODE,
                    "district_code": code,
                    "year_gregorian": base_year + horizon,
                    "value": value,
                    "lower": float(min(value, round(lower))),
                    "upper": float(max(value, round(upper))),
                    "model_version": selected,
                    "generated_at": generated_at,
                    "base_period": base_period,
                    "base_value": base_value,
                    "entering": entering,
                    "ageing_out": ageing_out,
                    "net_change": net_change,
                    "size_class": classes[code].value,
                    "total_population": history.totals[base_year][code],
                }
            )
    return rows


def _accuracy_json(
    items: Sequence[HorizonAccuracy], coverage: CoverageReport | None
) -> list[dict[str, object]]:
    by_horizon = coverage.by_horizon if coverage is not None else {}
    return [
        {
            "horizon_years": item.horizon,
            "samples": item.samples,
            "mape_percent": round(item.mape_percent, 2),
            "p90_ape_percent": round(item.p90_ape_percent, 2),
            "bias_percent": round(item.bias_percent, 2),
            "interval_coverage": (
                round(by_horizon[item.horizon][0], 3) if item.horizon in by_horizon else None
            ),
        }
        for item in items
    ]


def _class_coverage(coverage: CoverageReport | None, klass: SizeClass) -> float | None:
    if coverage is None or klass not in coverage.by_size_class:
        return None
    return round(coverage.by_size_class[klass][0], 3)


def _model_card(
    *,
    source: Path,
    history: RegistrationHistory,
    selected: str,
    accuracy: dict[str, tuple[HorizonAccuracy, ...]],
    gate_reasons: tuple[str, ...],
    widths: dict[tuple[int, SizeClass], IntervalWidth],
    coverage: CoverageReport | None,
    origins: list[int],
    base_period: str,
    horizon_years: int,
    window_years: int,
    generated_at: datetime,
) -> dict[str, object]:
    return {
        "model_version": selected,
        "generated_at": generated_at.isoformat(),
        "metric_code": METRIC_CODE,
        "evaluation": {
            "method": (
                "Hamilton-Perry cohort change ratios on single-year ages, median of the "
                f"{window_years}-year window, summed over ages 18-35"
                if selected == COHORT_VERSION
                else selected
            ),
            "selected_model": selected,
            "baseline_model": NAIVE_VERSION,
            "base_period": base_period,
            "target_coverage": TARGET_COVERAGE,
            "error_quantile": ERROR_QUANTILE,
            "rolling_coverage": round(coverage.coverage, 3) if coverage else None,
            "rolling_samples": coverage.samples if coverage else None,
            "small_area_coverage": _class_coverage(coverage, SizeClass.SMALL),
            "candidates": [
                {
                    "model": name,
                    "accuracy": _accuracy_json(items, coverage if name == selected else None),
                }
                for name, items in sorted(accuracy.items())
            ],
            "source_sha256": _sha256(source),
            "references": list(REFERENCES),
            "limitations": list(LIMITATIONS),
        },
        "parameters": {
            "snapshot_month": history.month,
            "window_years": window_years,
            "horizon_years": horizon_years,
            "backtest_origins": origins,
            "snapshot_years": sorted(history.snapshots),
            "small_area_population": 10_000,
            "target_coverage": TARGET_COVERAGE,
            "error_quantile": ERROR_QUANTILE,
        },
        "gate": {"passed": True, "reasons": list(gate_reasons)},
        "interval_widths": [
            {
                "horizon_years": item.horizon,
                "size_class": item.size_class.value,
                "samples": item.samples,
                "pooled": item.pooled,
                "absolute_error": round(item.absolute_error, 4),
            }
            for _, item in sorted(widths.items())
        ],
        "rolling_coverage": None
        if coverage is None
        else {
            "coverage": round(coverage.coverage, 3),
            "samples": coverage.samples,
            "by_horizon": [
                {"horizon_years": h, "coverage": round(share, 3), "samples": count}
                for h, (share, count) in coverage.by_horizon.items()
            ],
            "by_size_class": [
                {"size_class": klass.value, "coverage": round(share, 3), "samples": count}
                for klass, (share, count) in sorted(coverage.by_size_class.items())
            ],
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_forecast_table(table: pa.Table, horizon_years: int) -> None:
    """Refuse a table that does not cover every district and horizon with sound intervals."""

    rows = table.to_pylist()
    districts = {row["district_code"] for row in rows}
    if len(districts) != DISTRICT_COUNT or len(rows) != DISTRICT_COUNT * horizon_years:
        raise PublicationError("forecast does not cover every district and horizon")
    if any(not row["lower"] <= row["value"] <= row["upper"] for row in rows):
        raise PublicationError("a forecast interval does not contain its point")
