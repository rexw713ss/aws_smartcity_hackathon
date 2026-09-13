"""Which unit makes a comparison mean something. Doc 30, stage 2.

Absolute counts answer "how big", which is usually the one thing the reader
already knows. Comparing Banqiao with Pinglin in persons restates that Banqiao
is larger; comparing them as an index against their own baseline shows which one
is actually losing its young people. This module picks that unit from the shape
`data_shape.profile_series` measured, and applies it deterministically.

Every transformed value is computed here, in code, from published values. The
model never performs arithmetic; it is told which measure was chosen and why, so
the prose and the axis agree.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import AnalysisOperation, DecomposedQuery, ObservationSeries
from youth_compass.agent.data_shape import Granularity, SeriesProfile
from youth_compass.ontology import NameLanguage

# Above this ratio between the largest and smallest entity, a shared axis in
# absolute units is dominated by size and shows nothing about behaviour.
_WIDE_SPREAD_RATIO = 4.0
_MIN_YEARS_FOR_YOY = 2
_MONTHS_PER_YEAR = 12
_INDEX_BASE = 100.0
_PER_1000 = 1000.0


class Transform(StrEnum):
    """Allowlisted measures. Anything outside this list is not expressible."""

    RAW = "raw"
    INDEX_100 = "index_100"
    PCT_CHANGE = "pct_change"
    YOY_CHANGE = "yoy_change"
    SHARE_OF_TOTAL = "share_of_total"
    PER_1000 = "per_1000"


class Measure(BaseModel):
    """The unit one visualization will speak in, with the reason it was chosen."""

    model_config = ConfigDict(frozen=True)

    transform: Transform
    unit_code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    # Shown under the chart. A reader who disagrees with the axis can see the
    # rule that produced it instead of guessing.
    rationale: str = Field(min_length=1)
    # Set when the measure is relative to one period, so a caption can name it.
    baseline_period: str | None = None


class MeasuredPoint(BaseModel):
    """One transformed value that keeps the published value it came from."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str | None = None
    period: str
    value: float
    source_value: float


def choose_measure(
    profile: SeriesProfile,
    decomposition: DecomposedQuery,
    *,
    language: NameLanguage = NameLanguage.ENGLISH,
    denominators: Mapping[str, float] | None = None,
) -> Measure:
    """Pick the unit that makes the question's comparison legible."""

    if profile.unit_code == "percent":
        # A rate is already normalized. Dividing it by population, indexing it,
        # or taking a percent of it only hides the percentage points that moved.
        return _measure(Transform.RAW, language, profile)
    wide = profile.spread_ratio is not None and profile.spread_ratio >= _WIDE_SPREAD_RATIO
    multi_entity = profile.entity_count >= 2
    collapsed = AnalysisOperation.COMPARE_ENTITIES in decomposition.operations

    if multi_entity and wide and _covers_every_entity(profile, denominators):
        return _measure(Transform.PER_1000, language)
    if collapsed:
        # One number per entity. A percentage is the only way a small district's
        # movement competes with a large one's on the same bar axis.
        return _measure(Transform.PCT_CHANGE if wide else Transform.RAW, language, profile)
    if profile.granularity is Granularity.MONTH and _distinct_years(profile) >= _MIN_YEARS_FOR_YOY:
        # Month-on-month movement in a seasonal series is mostly the season.
        return _measure(Transform.YOY_CHANGE, language)
    if multi_entity and wide and profile.period_count >= 2:
        return _measure(
            Transform.INDEX_100,
            language,
            baseline_period=profile.periods[0] if profile.periods else None,
        )
    return _measure(Transform.RAW, language, profile)


def apply_measure(
    series: ObservationSeries,
    measure: Measure,
    *,
    denominators: Mapping[str, float] | None = None,
) -> tuple[MeasuredPoint, ...]:
    """Transform published values into the chosen measure, dropping nothing silently.

    A point whose baseline is zero or missing cannot be expressed as a ratio, so
    it is omitted rather than given a substituted denominator. Callers compare
    the returned length against the series to report what fell away.
    """

    by_entity: dict[str, list[MeasuredPoint]] = {}
    for point in series.points:
        by_entity.setdefault(point.entity_id, []).append(
            MeasuredPoint(
                entity_id=point.entity_id,
                entity_name=point.entity_name,
                period=point.period,
                value=point.value,
                source_value=point.value,
            )
        )
    ordered = {
        entity_id: sorted(points, key=lambda point: point.period)
        for entity_id, points in sorted(by_entity.items())
    }
    match measure.transform:
        case Transform.RAW:
            return tuple(point for points in ordered.values() for point in points)
        case Transform.INDEX_100:
            return _rescaled(ordered, _INDEX_BASE)
        case Transform.PCT_CHANGE:
            return _collapsed_change(ordered)
        case Transform.YOY_CHANGE:
            return _year_over_year(ordered)
        case Transform.SHARE_OF_TOTAL:
            return _share_of_total(ordered)
        case Transform.PER_1000:
            return _per_denominator(ordered, denominators)


def _rescaled(
    ordered: Mapping[str, Sequence[MeasuredPoint]], base: float
) -> tuple[MeasuredPoint, ...]:
    """Restate each entity against its own first published value."""

    output: list[MeasuredPoint] = []
    for points in ordered.values():
        baseline = points[0].source_value
        if not baseline:
            continue
        output.extend(
            point.model_copy(update={"value": base * point.source_value / baseline})
            for point in points
        )
    return tuple(output)


def _collapsed_change(
    ordered: Mapping[str, Sequence[MeasuredPoint]],
) -> tuple[MeasuredPoint, ...]:
    """One percentage per entity, carried on the period it ends at."""

    output: list[MeasuredPoint] = []
    for points in ordered.values():
        first, last = points[0], points[-1]
        if len(points) < 2 or not first.source_value:
            continue
        change = 100.0 * (last.source_value - first.source_value) / first.source_value
        output.append(last.model_copy(update={"value": change}))
    return tuple(output)


def _year_over_year(
    ordered: Mapping[str, Sequence[MeasuredPoint]],
) -> tuple[MeasuredPoint, ...]:
    """Compare each month with the same month a year earlier, never its neighbour."""

    output: list[MeasuredPoint] = []
    for points in ordered.values():
        by_period = {point.period: point for point in points}
        for point in points:
            prior = by_period.get(_shift_year(point.period))
            if prior is None or not prior.source_value:
                continue
            change = 100.0 * (point.source_value - prior.source_value) / prior.source_value
            output.append(point.model_copy(update={"value": change}))
    return tuple(output)


def _share_of_total(
    ordered: Mapping[str, Sequence[MeasuredPoint]],
) -> tuple[MeasuredPoint, ...]:
    """Each entity's percentage of the total the shown entities sum to, per period."""

    totals: dict[str, float] = {}
    for points in ordered.values():
        for point in points:
            totals[point.period] = totals.get(point.period, 0.0) + point.source_value
    return tuple(
        point.model_copy(update={"value": 100.0 * point.source_value / totals[point.period]})
        for points in ordered.values()
        for point in points
        if totals.get(point.period)
    )


def _per_denominator(
    ordered: Mapping[str, Sequence[MeasuredPoint]],
    denominators: Mapping[str, float] | None,
) -> tuple[MeasuredPoint, ...]:
    """Express each value against its entity's own denominator."""

    if not denominators:
        raise ValueError("a per-1,000 measure needs a denominator for every entity")
    return tuple(
        point.model_copy(update={"value": _PER_1000 * point.source_value / denominator})
        for points in ordered.values()
        for point in points
        if (denominator := denominators.get(point.entity_id))
    )


def _covers_every_entity(profile: SeriesProfile, denominators: Mapping[str, float] | None) -> bool:
    """A rate is only honest when every entity on the axis has a denominator."""

    if not denominators:
        return False
    return all(denominators.get(signal.entity_id) not in (None, 0) for signal in profile.signals)


def _distinct_years(profile: SeriesProfile) -> int:
    return len({period[:4] for period in profile.periods})


def _shift_year(period: str) -> str:
    year, _, month = period.partition("-")
    return f"{int(year) - 1:04d}-{month}" if month else str(int(year) - 1)


def _measure(
    transform: Transform,
    language: NameLanguage,
    profile: SeriesProfile | None = None,
    *,
    baseline_period: str | None = None,
) -> Measure:
    label, rationale = _TEXT[_language_key(language)][transform]
    unit = _UNITS[transform]
    if transform is Transform.RAW and profile is not None:
        unit = profile.unit_code
    return Measure(
        transform=transform,
        unit_code=unit,
        label=label,
        rationale=rationale,
        baseline_period=baseline_period,
    )


def _language_key(language: NameLanguage) -> str:
    if language is NameLanguage.ZH_HANT:
        return "zh"
    if language is NameLanguage.VIETNAMESE:
        return "vi"
    return "en"


_UNITS: dict[Transform, str] = {
    Transform.RAW: "count",
    Transform.INDEX_100: "index_100",
    Transform.PCT_CHANGE: "percent",
    Transform.YOY_CHANGE: "percent",
    Transform.SHARE_OF_TOTAL: "percent",
    Transform.PER_1000: "per_1000",
}

_TEXT: dict[str, dict[Transform, tuple[str, str]]] = {
    "en": {
        Transform.RAW: (
            "Published value",
            "The entities shown are of comparable size, so published values compare directly.",
        ),
        Transform.INDEX_100: (
            "Index (first period = 100)",
            "These places differ too much in size to share an absolute axis, so each is shown "
            "against its own starting value.",
        ),
        Transform.PCT_CHANGE: (
            "Change (%)",
            "Percentages let a small district's movement be compared with a large one's.",
        ),
        Transform.YOY_CHANGE: (
            "Year-on-year change (%)",
            "Monthly figures are seasonal, so each month is compared with the same month a year "
            "earlier rather than with the month before it.",
        ),
        Transform.SHARE_OF_TOTAL: (
            "Share of total (%)",
            "Each entity is shown as its share of the total the displayed entities sum to.",
        ),
        Transform.PER_1000: (
            "Per 1,000 residents",
            "A rate removes population size, so the comparison is about intensity, not headcount.",
        ),
    },
    "zh": {
        Transform.RAW: ("已發布數值", "所呈現地區規模相近，可直接比較原始數值。"),  # noqa: RUF001
        Transform.INDEX_100: (
            "指數（首期＝100）",  # noqa: RUF001
            "各地區規模差異過大，無法共用絕對值座標軸，因此各自對照自身起始值呈現。",  # noqa: RUF001
        ),
        Transform.PCT_CHANGE: (
            "變化率（%）",  # noqa: RUF001
            "以百分比呈現，小區的變動才能與大區相互比較。",  # noqa: RUF001
        ),
        Transform.YOY_CHANGE: (
            "年增率（%）",  # noqa: RUF001
            "月資料具季節性，因此與去年同月比較，而非與上個月比較。",  # noqa: RUF001
        ),
        Transform.SHARE_OF_TOTAL: (
            "占比（%）",  # noqa: RUF001
            "各地區以其占所列地區合計的比例呈現。",
        ),
        Transform.PER_1000: (
            "每千人",
            "改以比率呈現可排除人口規模影響，比較的是強度而非人數。",  # noqa: RUF001
        ),
    },
    "vi": {
        Transform.RAW: (
            "Giá trị đã công bố",
            "Các địa bàn hiển thị có quy mô tương đương nên so sánh trực tiếp giá trị gốc.",
        ),
        Transform.INDEX_100: (
            "Chỉ số (kỳ đầu = 100)",
            "Các địa bàn chênh lệch quy mô quá lớn để dùng chung trục giá trị tuyệt đối, nên mỗi "
            "nơi được quy về mốc ban đầu của chính nó.",
        ),
        Transform.PCT_CHANGE: (
            "Mức thay đổi (%)",
            "Dùng phần trăm để biến động của một quận nhỏ có thể so được với một quận lớn.",
        ),
        Transform.YOY_CHANGE: (
            "Thay đổi so với cùng kỳ (%)",
            "Số liệu tháng có tính mùa vụ nên mỗi tháng được so với cùng tháng năm trước, không "
            "phải với tháng liền kề.",
        ),
        Transform.SHARE_OF_TOTAL: (
            "Tỷ trọng (%)",
            "Mỗi địa bàn hiển thị theo tỷ trọng trong tổng của các địa bàn được trình bày.",
        ),
        Transform.PER_1000: (
            "Trên 1.000 dân",
            "Dùng tỷ suất để loại bỏ ảnh hưởng quy mô dân số, so sánh cường độ chứ không phải "
            "số người.",
        ),
    },
}


__all__ = ["Measure", "MeasuredPoint", "Transform", "apply_measure", "choose_measure"]
