"""Deterministic shape, signal, and defect profile of the rows an answer used.

Doc 30, stage 1. The ingestion profiler in `youth_compass.ingestion.csv_profiler`
describes a raw file before it is published. This module describes the small
result set an answer actually retrieved, at the moment the agent has to decide
what — if anything — is worth plotting.

Nothing here interpolates, smooths, or repairs a value. Every field is computed
from the returned points, so a caller can defend any decision made from it.
Freshness, district coverage, and the estimated-value caveat stay owned by
`youth_compass.agent.limitations`; this module exposes the raw inputs it needs
for chart selection instead of restating those narratives.
"""

import re
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from itertools import pairwise
from statistics import median, pstdev

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import ObservationPoint, ObservationSeries
from youth_compass.domain.types import WarningSeverity
from youth_compass.ontology import resolve_district_name

# A series whose every entity moved less than this is flat: any trend line drawn
# through it would invite the reader to see a story that is not in the data.
_FLAT_CHANGE_RATIO = 0.02
# Below this share of the entity x period grid, a multi-series line spends more
# pixels on gaps than on values.
_SPARSE_COVERAGE_RATIO = 0.7
# The newest period is treated as still being collected when materially fewer
# entities report it than reported the period before.
_PARTIAL_PERIOD_RATIO = 0.8
# A step this many times the typical step, and this large in relative terms, is
# reported as a level shift rather than accepted as an event.
_LEVEL_SHIFT_STEP_MULTIPLE = 5.0
_LEVEL_SHIFT_MIN_RATIO = 0.25
_MIN_STEPS_FOR_LEVEL_SHIFT = 3

_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_COUNT_UNITS = frozenset({"persons", "people", "households", "count"})


class Granularity(StrEnum):
    """Period shape shared by the returned points."""

    YEAR = "year"
    MONTH = "month"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Direction(StrEnum):
    """First-to-last movement of one entity."""

    INCREASED = "increased"
    DECREASED = "decreased"
    UNCHANGED = "unchanged"


class IssueCode(StrEnum):
    """Defects that change whether, or how, a result may be plotted."""

    DUPLICATE_OBSERVATION = "DUPLICATE_OBSERVATION"
    NEGATIVE_COUNT = "NEGATIVE_COUNT"
    PARTIAL_LATEST_PERIOD = "PARTIAL_LATEST_PERIOD"
    LEVEL_SHIFT = "LEVEL_SHIFT"
    SPARSE_COVERAGE = "SPARSE_COVERAGE"


class DataIssue(BaseModel):
    """One defect, with enough keys for a caller to exclude exactly what it names."""

    model_config = ConfigDict(frozen=True)

    code: IssueCode
    message: str = Field(min_length=1)
    severity: WarningSeverity = WarningSeverity.WARNING
    entity_ids: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()


class EntitySignal(BaseModel):
    """How much one entity actually moved, relative to its own volatility."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str | None = None
    observation_count: int = Field(ge=1)
    first_period: str
    last_period: str
    first_value: float
    last_value: float
    net_change: float
    # None when the first value is zero: a ratio against zero is undefined, and
    # substituting one would invent the very number this module refuses to add.
    net_change_ratio: float | None = None
    # |net change| over the standard deviation of consecutive steps. None when a
    # single step, or a perfectly regular series, leaves no noise to divide by.
    signal_to_noise: float | None = None
    direction: Direction


class SeriesProfile(BaseModel):
    """Everything stages 2-4 of doc 30 need to decide what to plot."""

    model_config = ConfigDict(frozen=True)

    metric_code: str
    unit_code: str
    entity_count: int = Field(default=0, ge=0)
    period_count: int = Field(default=0, ge=0)
    periods: tuple[str, ...] = ()
    granularity: Granularity = Granularity.UNKNOWN
    # Distinct (entity, period) pairs over the full grid those entities and
    # periods would span.
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    value_min: float | None = None
    value_max: float | None = None
    value_median: float | None = None
    # Cross-entity dispersion in the newest period at least two entities share.
    comparison_period: str | None = None
    spread_ratio: float | None = None
    coefficient_of_variation: float | None = None
    signals: tuple[EntitySignal, ...] = ()
    is_flat: bool = False
    estimated_point_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    unmapped_entity_ids: tuple[str, ...] = ()
    issues: tuple[DataIssue, ...] = ()

    @property
    def has_blocking_issue(self) -> bool:
        """True when something found here makes a plot misleading on its face."""

        return any(issue.severity is WarningSeverity.ERROR for issue in self.issues)

    def issue(self, code: IssueCode) -> DataIssue | None:
        return next((item for item in self.issues if item.code is code), None)


def profile_series(series: ObservationSeries) -> SeriesProfile:
    """Describe a retrieved observation series without altering any value."""

    points = series.points
    if not points:
        return SeriesProfile(metric_code=series.metric_code, unit_code=series.unit_code)

    by_entity: dict[str, list[ObservationPoint]] = {}
    for point in points:
        by_entity.setdefault(point.entity_id, []).append(point)
    periods = tuple(sorted({point.period for point in points}))
    values = [point.value for point in points]
    pairs = {(point.entity_id, point.period) for point in points}
    grid = len(by_entity) * len(periods)

    signals = tuple(
        _entity_signal(entity_id, entity_points)
        for entity_id, entity_points in sorted(by_entity.items())
    )
    comparison_period, spread_ratio, variation = _dispersion(by_entity, periods)
    ratios = [
        abs(signal.net_change_ratio) for signal in signals if signal.net_change_ratio is not None
    ]
    coverage_ratio = len(pairs) / grid if grid else 0.0

    return SeriesProfile(
        metric_code=series.metric_code,
        unit_code=series.unit_code,
        entity_count=len(by_entity),
        period_count=len(periods),
        periods=periods,
        granularity=_granularity(periods),
        coverage_ratio=coverage_ratio,
        value_min=min(values),
        value_max=max(values),
        value_median=median(values),
        comparison_period=comparison_period,
        spread_ratio=spread_ratio,
        coefficient_of_variation=variation,
        signals=signals,
        is_flat=bool(ratios) and max(ratios) < _FLAT_CHANGE_RATIO,
        estimated_point_ratio=sum(point.estimated_value > 0 for point in points) / len(points),
        unmapped_entity_ids=tuple(
            entity_id
            for entity_id in sorted(by_entity)
            if resolve_district_name(entity_id).district is None
        ),
        issues=_issues(series, by_entity, periods, pairs, coverage_ratio),
    )


def _entity_signal(entity_id: str, points: Sequence[ObservationPoint]) -> EntitySignal:
    ordered = sorted(points, key=lambda point: point.period)
    first, last = ordered[0], ordered[-1]
    net_change = last.value - first.value
    steps = [right.value - left.value for left, right in pairwise(ordered)]
    noise = pstdev(steps) if len(steps) > 1 else 0.0
    if net_change > 0:
        direction = Direction.INCREASED
    elif net_change < 0:
        direction = Direction.DECREASED
    else:
        direction = Direction.UNCHANGED
    return EntitySignal(
        entity_id=entity_id,
        entity_name=next((point.entity_name for point in ordered if point.entity_name), None),
        observation_count=len(ordered),
        first_period=first.period,
        last_period=last.period,
        first_value=first.value,
        last_value=last.value,
        net_change=net_change,
        net_change_ratio=net_change / first.value if first.value else None,
        signal_to_noise=abs(net_change) / noise if noise else None,
        direction=direction,
    )


def _dispersion(
    by_entity: dict[str, list[ObservationPoint]], periods: Sequence[str]
) -> tuple[str | None, float | None, float | None]:
    """Compare entities inside one period, never across periods of different age."""

    if len(by_entity) < 2:
        return None, None, None
    for period in reversed(periods):
        values = [
            point.value
            for points in by_entity.values()
            for point in points
            if point.period == period
        ]
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        smallest, largest = min(values), max(values)
        return (
            period,
            largest / smallest if smallest > 0 else None,
            pstdev(values) / mean if mean else None,
        )
    return None, None, None


def _granularity(periods: Sequence[str]) -> Granularity:
    years = all(_YEAR.fullmatch(period) for period in periods)
    months = all(_MONTH.fullmatch(period) for period in periods)
    if years:
        return Granularity.YEAR
    if months:
        return Granularity.MONTH
    if any(_YEAR.fullmatch(period) or _MONTH.fullmatch(period) for period in periods):
        return Granularity.MIXED
    return Granularity.UNKNOWN


def _issues(
    series: ObservationSeries,
    by_entity: dict[str, list[ObservationPoint]],
    periods: Sequence[str],
    pairs: set[tuple[str, str]],
    coverage_ratio: float,
) -> tuple[DataIssue, ...]:
    issues: list[DataIssue] = []
    duplicates = _duplicates(series.points, pairs)
    if duplicates is not None:
        issues.append(duplicates)
    negatives = _negatives(series)
    if negatives is not None:
        issues.append(negatives)
    partial = _partial_latest_period(by_entity, periods)
    if partial is not None:
        issues.append(partial)
    issues.extend(_level_shifts(by_entity))
    if len(by_entity) > 1 and len(periods) > 1 and coverage_ratio < _SPARSE_COVERAGE_RATIO:
        issues.append(
            DataIssue(
                code=IssueCode.SPARSE_COVERAGE,
                message=(
                    f"only {coverage_ratio:.0%} of the {len(by_entity)} x {len(periods)} "
                    "entity-period grid was published"
                ),
            )
        )
    return tuple(issues)


def _duplicates(
    points: Sequence[ObservationPoint], pairs: set[tuple[str, str]]
) -> DataIssue | None:
    """Two values for one entity and period mean the query aggregated wrongly."""

    if len(points) == len(pairs):
        return None
    counts = Counter((point.entity_id, point.period) for point in points)
    repeated = sorted(pair for pair, seen in counts.items() if seen > 1)
    return DataIssue(
        code=IssueCode.DUPLICATE_OBSERVATION,
        # An answer cannot choose between two conflicting grounded values, so
        # this is an error rather than a caveat.
        severity=WarningSeverity.ERROR,
        message=f"{len(repeated)} entity-period pairs carry more than one published value",
        entity_ids=tuple(sorted({entity_id for entity_id, _ in repeated})),
        periods=tuple(sorted({period for _, period in repeated})),
    )


def _negatives(series: ObservationSeries) -> DataIssue | None:
    if not _is_count_metric(series):
        return None
    affected = sorted({point.entity_id for point in series.points if point.value < 0})
    if not affected:
        return None
    return DataIssue(
        code=IssueCode.NEGATIVE_COUNT,
        severity=WarningSeverity.ERROR,
        message=f"{len(affected)} entities report a negative value on a count metric",
        entity_ids=tuple(affected),
    )


def _is_count_metric(series: ObservationSeries) -> bool:
    return series.metric_code.endswith("_count") or series.unit_code.casefold() in _COUNT_UNITS


def _partial_latest_period(
    by_entity: dict[str, list[ObservationPoint]], periods: Sequence[str]
) -> DataIssue | None:
    """Catch the newest period still being collected before a line plots its cliff."""

    if len(periods) < 2 or len(by_entity) < 2:
        return None
    latest, previous = periods[-1], periods[-2]
    reporting = {
        period: sum(
            any(point.period == period for point in points) for points in by_entity.values()
        )
        for period in (latest, previous)
    }
    if not reporting[previous] or reporting[latest] >= reporting[previous] * _PARTIAL_PERIOD_RATIO:
        return None
    return DataIssue(
        code=IssueCode.PARTIAL_LATEST_PERIOD,
        message=(
            f"{latest} is reported by {reporting[latest]} of the {reporting[previous]} entities "
            f"that reported {previous}, so it is probably still being collected"
        ),
        periods=(latest,),
    )


def _level_shifts(by_entity: dict[str, list[ObservationPoint]]) -> tuple[DataIssue, ...]:
    """Flag a jump far outside a series' own step distribution."""

    issues: list[DataIssue] = []
    for entity_id, points in sorted(by_entity.items()):
        ordered = sorted(points, key=lambda point: point.period)
        steps = [
            (right.period, right.value - left.value, left.value)
            for left, right in pairwise(ordered)
        ]
        if len(steps) < _MIN_STEPS_FOR_LEVEL_SHIFT:
            continue
        typical = median([abs(change) for _, change, _ in steps])
        if typical <= 0:
            continue
        flagged = tuple(
            period
            for period, change, base in steps
            if abs(change) > typical * _LEVEL_SHIFT_STEP_MULTIPLE
            and base
            and abs(change / base) > _LEVEL_SHIFT_MIN_RATIO
        )
        if flagged:
            issues.append(
                DataIssue(
                    code=IssueCode.LEVEL_SHIFT,
                    message=(
                        f"{entity_id} jumps far outside its usual step size at "
                        f"{', '.join(flagged)}, which often marks a definition change"
                    ),
                    entity_ids=(entity_id,),
                    periods=flagged,
                )
            )
    return tuple(issues)


__all__ = [
    "DataIssue",
    "Direction",
    "EntitySignal",
    "Granularity",
    "IssueCode",
    "SeriesProfile",
    "profile_series",
]
