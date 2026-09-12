"""Deterministic visualization specs built from grounded agent results."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from youth_compass.agent.contracts import (
    CandidateInsight,
    DatasetInspection,
    EntityComparison,
    ObservationSeries,
    RegionScheme,
    VisualizationColumn,
    VisualizationEncoding,
    VisualizationSpec,
    VisualizationType,
    VisualizationValue,
)
from youth_compass.ontology import (
    NameLanguage,
    display_name,
    humanize_code,
    localized_district_name,
    question_language,
    readable_entity_name,
    readable_feature_name,
    resolve_district_name,
)
from youth_compass.ports import ForecastResult

_MAX_CHART_ROWS = 200
_MAX_TABLE_ROWS = 200
_MIN_BAR_CATEGORIES = 2
_MIN_LINE_PERIODS = 2
_MIN_MAP_REGIONS = 2
_MAX_BAR_CATEGORIES = 12
_MAX_CONTRIBUTIONS = 10
_MAX_LINE_SERIES = 8
_MAX_POINTS_PER_LINE = 48


@dataclass(frozen=True, slots=True)
class MapReading:
    """One district-keyed figure a choropleth may shade."""

    entity_id: str
    entity_name: str | None
    value: float | None
    rank: int | None = None
    period: str | None = None


class VisualizationBuilder:
    """Map typed results to a small frontend-independent template allowlist."""

    def decision(
        self,
        question: str,
        candidates: tuple[CandidateInsight, ...],
        citation_ids: tuple[str, ...],
    ) -> tuple[VisualizationSpec, ...]:
        labels = _labels(question)
        language = _language(question)
        ranked_rows: list[dict[str, VisualizationValue]] = [
            {
                "rank": candidate.rank,
                "entity_id": candidate.entity_id,
                "entity_name": readable_entity_name(
                    candidate.entity_id, candidate.entity_name, language
                ),
                "score": candidate.score,
                "eligible": candidate.eligible,
            }
            for candidate in candidates
        ]
        eligible_rows = [row for row in ranked_rows if row["eligible"] and row["score"] is not None]
        specs: list[VisualizationSpec] = []
        ranking_is_useful = (
            len(eligible_rows) >= _MIN_BAR_CATEGORIES
            and len({row["score"] for row in eligible_rows}) > 1
        )
        if ranking_is_useful:
            specs.append(
                VisualizationSpec(
                    visualization_id="candidate-ranking",
                    type=VisualizationType.RANKING_BAR,
                    title=labels["ranking_title"],
                    x=_encoding("score", labels["score"], "quantitative", "score_0_100"),
                    y=_encoding("entity_name", labels["candidate"], "nominal"),
                    rows=tuple(eligible_rows[:_MAX_BAR_CATEGORIES]),
                    citation_ids=citation_ids,
                    truncated=len(eligible_rows) > _MAX_BAR_CATEGORIES,
                )
            )
        top = next((candidate for candidate in candidates if candidate.rank == 1), None)
        if top is not None and top.contributions:
            contribution_rows: list[dict[str, VisualizationValue]] = [
                {
                    "feature_code": item.feature_code,
                    "feature_name": readable_feature_name(item.feature_code, item.feature_name),
                    "raw_value": item.raw_value,
                    "effective_weight": item.effective_weight,
                    "points": item.points,
                }
                for item in top.contributions
                if item.points > 0
            ]
            contribution_rows.sort(
                key=lambda row: (-float(row["points"] or 0), str(row["feature_name"]))
            )
            if len(contribution_rows) >= _MIN_BAR_CATEGORIES:
                specs.append(
                    VisualizationSpec(
                        visualization_id="top-candidate-contributions",
                        type=VisualizationType.CONTRIBUTION_BAR,
                        title=labels["contribution_title"],
                        x=_encoding("points", labels["points"], "quantitative", "score_points"),
                        y=_encoding("feature_name", labels["feature"], "nominal"),
                        rows=tuple(contribution_rows[:_MAX_CONTRIBUTIONS]),
                        citation_ids=citation_ids,
                        truncated=len(contribution_rows) > _MAX_CONTRIBUTIONS,
                    )
                )
        # A table is a fallback, or an audit surface for candidates excluded
        # from the ranking. Do not duplicate a complete useful ranking bar.
        if ranked_rows and (
            not ranking_is_useful
            or len(eligible_rows) != len(ranked_rows)
            or len(eligible_rows) > _MAX_BAR_CATEGORIES
        ):
            specs.append(
                VisualizationSpec(
                    visualization_id="candidate-ranking-table",
                    type=VisualizationType.DATA_TABLE,
                    title=labels["ranking_table_title"],
                    columns=(
                        _column("rank", labels["rank"]),
                        _column("entity_name", labels["candidate"]),
                        _column("score", labels["score"], "score_0_100"),
                        _column("eligible", labels["eligible"]),
                    ),
                    rows=tuple(ranked_rows[:_MAX_TABLE_ROWS]),
                    citation_ids=citation_ids,
                    truncated=len(ranked_rows) > _MAX_TABLE_ROWS,
                )
            )
        mapped = (
            _choropleth(
                visualization_id="candidate-ranking-map",
                title=labels["ranking_map_title"],
                labels=labels,
                language=language,
                value_label=labels["score"],
                unit="score_0_100",
                readings=[
                    MapReading(
                        entity_id=candidate.entity_id,
                        entity_name=candidate.entity_name,
                        value=candidate.score,
                        rank=candidate.rank,
                    )
                    for candidate in candidates
                    if candidate.eligible and candidate.score is not None
                ],
                citation_ids=citation_ids,
            )
            if _wants_map(question)
            else None
        )
        if mapped is not None:
            specs.append(mapped)
        return tuple(specs)

    def observations(
        self,
        question: str,
        series: ObservationSeries,
        comparison: EntityComparison | None,
        citation_ids: tuple[str, ...],
    ) -> tuple[VisualizationSpec, ...]:
        labels = _labels(question)
        language = _language(question)
        rows: list[dict[str, VisualizationValue]] = [
            {
                "period": point.period,
                "entity_id": point.entity_id,
                "entity_name": readable_entity_name(point.entity_id, point.entity_name, language),
                "value": point.value,
                "estimated_value": point.estimated_value,
            }
            for point in series.points
        ]
        metric_title = f"{humanize_code(series.metric_code)} {labels['trend_suffix']}"
        chart_rows, excluded_rows = _complete_series_rows(rows)
        chart_rows = _insert_monthly_gaps(chart_rows)
        chart_rows, sampled_rows = _select_informative_line_rows(chart_rows)
        excluded_rows = excluded_rows or sampled_rows
        specs: list[VisualizationSpec] = []
        comparison_rows: list[dict[str, VisualizationValue]] = []
        if comparison is not None:
            comparison_rows = [
                {
                    "entity_id": change.entity_id,
                    "entity_name": readable_entity_name(
                        change.entity_id, change.entity_name, language
                    ),
                    "absolute_change": change.absolute_change,
                    "percent_change": change.percent_change,
                    "direction": change.direction,
                }
                for change in comparison.changes
                if change.observation_count >= _MIN_LINE_PERIODS
            ]
        comparison_is_useful = len(comparison_rows) >= _MIN_BAR_CATEGORIES
        comparison_rows.sort(
            key=lambda row: (
                -abs(float(row["absolute_change"] or 0)),
                str(row["entity_name"]),
            )
        )
        # A comparison question is answered most directly by one comparison
        # chart. A trend question gets a line. Avoid returning both by default.
        if comparison_is_useful:
            specs.append(
                VisualizationSpec(
                    visualization_id="entity-change-comparison",
                    type=VisualizationType.COMPARISON_BAR,
                    title=labels["comparison_title"],
                    x=_encoding("entity_name", labels["entity"], "nominal"),
                    y=_encoding(
                        "absolute_change",
                        labels["absolute_change"],
                        "quantitative",
                        series.unit_code,
                    ),
                    rows=tuple(comparison_rows[:_MAX_BAR_CATEGORIES]),
                    citation_ids=citation_ids,
                    truncated=len(comparison_rows) > _MAX_BAR_CATEGORIES,
                )
            )
        elif chart_rows:
            has_gaps = any(row.get("value") is None for row in chart_rows)
            specs.append(
                VisualizationSpec(
                    visualization_id="observation-trend",
                    type=VisualizationType.LINE,
                    title=metric_title,
                    description=_trend_description(language, sampled_rows, has_gaps),
                    x=_encoding("period", labels["period"], "temporal"),
                    y=_encoding("value", labels["value"], "quantitative", series.unit_code),
                    series_field="entity_name",
                    rows=tuple(chart_rows[:_MAX_CHART_ROWS]),
                    citation_ids=citation_ids,
                    truncated=excluded_rows or len(chart_rows) > _MAX_CHART_ROWS,
                )
            )
        # Observation rows are already available through the cited evidence.
        # Do not duplicate them as a long table; no chart is better than a weak
        # chart when the series is too sparse to visualize honestly.
        # A map is useful only for an explicitly spatial question. Use the
        # newest period shared by every mapped district, never a sparse global
        # maximum that silently drops lagging districts.
        period = _latest_common_period(series) if _wants_map(question) else None
        mapped = _choropleth(
            visualization_id="observation-map",
            title=f"{metric_title} · {period}" if period else metric_title,
            labels=labels,
            language=language,
            value_label=labels["value"],
            unit=series.unit_code,
            readings=[
                MapReading(
                    entity_id=point.entity_id,
                    entity_name=point.entity_name,
                    value=point.value,
                    period=point.period,
                )
                for point in series.points
                if point.period == period
            ],
            citation_ids=citation_ids,
            description=labels["map_description"],
        )
        if mapped is not None and comparison is None:
            specs.append(mapped)
        return tuple(specs)

    def inspection(
        self, question: str, inspection: DatasetInspection
    ) -> tuple[VisualizationSpec, ...]:
        labels = _labels(question)
        return (
            VisualizationSpec(
                visualization_id="dataset-coverage-table",
                type=VisualizationType.DATA_TABLE,
                title=labels["coverage_title"],
                columns=(
                    _column("dataset_id", labels["dataset"]),
                    _column("metric_name", labels["metric"]),
                    _column("period_start", labels["period_start"]),
                    _column("period_end", labels["period_end"]),
                    _column("entity_count", labels["entity_count"]),
                    _column("quality_score", labels["quality"]),
                ),
                rows=(
                    {
                        "dataset_id": inspection.dataset_id,
                        "metric_name": humanize_code(inspection.metric_code),
                        "period_start": inspection.period_start,
                        "period_end": inspection.period_end,
                        "entity_count": inspection.entity_count,
                        "quality_score": inspection.quality_score,
                    },
                ),
            ),
        )

    def forecast(
        self,
        question: str,
        result: ForecastResult,
        citation_ids: tuple[str, ...],
    ) -> tuple[VisualizationSpec, ...]:
        """Build a renderer-neutral forecast line and its accessible table fallback."""

        labels = _labels(question)
        language = _language(question)
        rows: list[dict[str, VisualizationValue]] = [
            {
                "period": str(point.year_gregorian),
                "entity_id": point.district_code,
                "entity_name": display_name(point.district_code, language),
                "value": point.value,
                "lower": point.lower,
                "upper": point.upper,
                "model_version": result.model_version,
            }
            for point in result.points
        ]
        chart_rows, excluded_rows = _complete_series_rows(rows)
        horizon = _latest_common_forecast_year(result) if _wants_map(question) else None
        mapped = _choropleth(
            visualization_id="forecast-map",
            title=(
                f"{humanize_code(result.metric_code)} {labels['forecast_suffix']} · {horizon}"
                if horizon is not None
                else f"{humanize_code(result.metric_code)} {labels['forecast_suffix']}"
            ),
            labels=labels,
            language=language,
            value_label=labels["forecast_value"],
            unit=None,
            readings=[
                MapReading(
                    entity_id=point.district_code,
                    entity_name=None,
                    value=point.value,
                    period=str(point.year_gregorian),
                )
                for point in result.points
                if point.year_gregorian == horizon
            ],
            citation_ids=citation_ids,
            description=labels["forecast_description"],
        )
        specs: list[VisualizationSpec] = []
        if chart_rows:
            specs.append(
                VisualizationSpec(
                    visualization_id="forecast-trend",
                    type=VisualizationType.LINE,
                    title=f"{humanize_code(result.metric_code)} {labels['forecast_suffix']}",
                    description=labels["forecast_description"],
                    x=_encoding("period", labels["period"], "temporal"),
                    y=_encoding("value", labels["forecast_value"], "quantitative"),
                    series_field="entity_name",
                    rows=tuple(chart_rows[:_MAX_CHART_ROWS]),
                    citation_ids=citation_ids,
                    truncated=excluded_rows or len(chart_rows) > _MAX_CHART_ROWS,
                )
            )
        if not specs or excluded_rows:
            specs.append(
                VisualizationSpec(
                    visualization_id="forecast-table",
                    type=VisualizationType.DATA_TABLE,
                    title=labels["forecast_table_title"],
                    columns=(
                        _column("period", labels["period"]),
                        _column("entity_name", labels["entity"]),
                        _column("value", labels["forecast_value"]),
                        _column("lower", labels["lower"]),
                        _column("upper", labels["upper"]),
                        _column("model_version", labels["model_version"]),
                    ),
                    rows=tuple(rows[:_MAX_TABLE_ROWS]),
                    citation_ids=citation_ids,
                    truncated=len(rows) > _MAX_TABLE_ROWS,
                )
            )
        if mapped is not None:
            specs.append(mapped)
        return tuple(specs)


def _complete_series_rows(
    rows: Sequence[dict[str, VisualizationValue]],
) -> tuple[list[dict[str, VisualizationValue]], bool]:
    """Keep entities with enough distinct periods to form a truthful line."""

    periods: dict[str, set[str]] = {}
    for row in rows:
        entity = str(row.get("entity_id") or row.get("entity_name") or "")
        period = row.get("period")
        if entity and isinstance(period, str):
            periods.setdefault(entity, set()).add(period)
    complete = {entity for entity, values in periods.items() if len(values) >= _MIN_LINE_PERIODS}
    selected_entities = set(
        sorted(complete, key=lambda entity: (-len(periods[entity]), entity))[:_MAX_LINE_SERIES]
    )
    selected = [
        row
        for row in rows
        if str(row.get("entity_id") or row.get("entity_name") or "") in selected_entities
    ]
    return selected, len(selected) != len(rows)


def _insert_monthly_gaps(
    rows: Sequence[dict[str, VisualizationValue]],
) -> list[dict[str, VisualizationValue]]:
    """Materialize absent months as null so a line renderer draws a real gap."""

    grouped: dict[str, list[dict[str, VisualizationValue]]] = {}
    for row in rows:
        entity = str(row.get("entity_id") or row.get("entity_name") or "")
        grouped.setdefault(entity, []).append(dict(row))
    output: list[dict[str, VisualizationValue]] = []
    for entity_rows in grouped.values():
        ordered = sorted(entity_rows, key=lambda row: str(row.get("period") or ""))
        for index, row in enumerate(ordered):
            output.append(row)
            if index == len(ordered) - 1:
                continue
            current = _month_index(row.get("period"))
            following = _month_index(ordered[index + 1].get("period"))
            if current is None or following is None or following - current <= 1:
                continue
            # One null is enough to break the segment. Avoid manufacturing a
            # large run of synthetic categories for a long publication hiatus.
            missing = current + 1
            output.append(
                {
                    "period": f"{missing // 12:04d}-{missing % 12 + 1:02d}",
                    "entity_id": row.get("entity_id"),
                    "entity_name": row.get("entity_name"),
                    "value": None,
                    "estimated_value": None,
                    "missing": True,
                }
            )
    return output


def _month_index(value: VisualizationValue) -> int | None:
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", str(value or ""))
    if match is None:
        return None
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def _select_informative_line_rows(
    rows: Sequence[dict[str, VisualizationValue]],
) -> tuple[list[dict[str, VisualizationValue]], bool]:
    """Bound long lines while preserving endpoints, extrema, jumps, and gaps."""

    grouped: dict[str, list[dict[str, VisualizationValue]]] = {}
    for row in rows:
        entity = str(row.get("entity_id") or row.get("entity_name") or "")
        grouped.setdefault(entity, []).append(dict(row))
    if not grouped:
        return [], False
    per_line = min(_MAX_POINTS_PER_LINE, max(12, _MAX_CHART_ROWS // len(grouped)))
    selected: list[dict[str, VisualizationValue]] = []
    sampled = False
    for entity_rows in grouped.values():
        ordered = sorted(entity_rows, key=lambda row: str(row.get("period") or ""))
        if len(ordered) <= per_line:
            selected.extend(ordered)
            continue
        sampled = True
        keep = {0, len(ordered) - 1}
        numeric = [
            (index, float(value))
            for index, row in enumerate(ordered)
            # Bind before testing so the narrowed value is the one converted.
            if isinstance(value := row.get("value"), int | float)
        ]
        if numeric:
            keep.add(min(numeric, key=lambda item: item[1])[0])
            keep.add(max(numeric, key=lambda item: item[1])[0])
        for index, row in enumerate(ordered):
            if row.get("value") is None:
                keep.update({max(0, index - 1), index, min(len(ordered) - 1, index + 1)})
        jumps = sorted(
            ((abs(right[1] - left[1]), right[0]) for left, right in pairwise(numeric)),
            reverse=True,
        )
        keep.update(index for _, index in jumps[:6])
        remaining = per_line - len(keep)
        if remaining > 0:
            step = (len(ordered) - 1) / (remaining + 1)
            keep.update(round(step * offset) for offset in range(1, remaining + 1))
        if len(keep) > per_line:
            # Critical points are ordered by time; retain the available budget
            # without changing their chronology.
            keep = set(sorted(keep)[:per_line])
        selected.extend(row for index, row in enumerate(ordered) if index in keep)
    return selected, sampled


def _trend_description(language: NameLanguage, sampled: bool, has_gaps: bool) -> str | None:
    if not sampled and not has_gaps:
        return None
    if language is NameLanguage.ZH_HANT:
        parts = []
        if sampled:
            parts.append("為了清楚呈現趨勢，圖表保留起點、終點、極值與最大變化點")  # noqa: RUF001
        if has_gaps:
            parts.append("線段中斷表示該期資料缺失，並非數值為零")  # noqa: RUF001
        return "；".join(parts) + "。"  # noqa: RUF001
    if language is NameLanguage.VIETNAMESE:
        parts = []
        if sampled:
            parts.append("Biểu đồ giữ lại điểm đầu, điểm cuối, cực trị và các thay đổi lớn")
        if has_gaps:
            parts.append("đoạn đứt thể hiện kỳ thiếu dữ liệu, không phải giá trị bằng 0")
        return ". ".join(parts) + "."
    parts = []
    if sampled:
        parts.append("Selected points preserve endpoints, extrema, and the largest changes")
    if has_gaps:
        parts.append("A break marks a missing period, not a zero value")
    return ". ".join(parts) + "."


def _latest_common_period(series: ObservationSeries) -> str | None:
    """Newest period shared by at least two resolvable districts."""

    by_district: dict[str, set[str]] = {}
    for point in series.points:
        district = resolve_district_name(point.entity_id).district
        if district is not None:
            by_district.setdefault(district.code, set()).add(point.period)
    if len(by_district) < _MIN_MAP_REGIONS:
        return None
    common = set.intersection(*by_district.values())
    return max(common) if common else None


def _latest_common_forecast_year(result: ForecastResult) -> int | None:
    """Newest forecast year shared by at least two mapped districts."""

    by_district: dict[str, set[int]] = {}
    for point in result.points:
        district = resolve_district_name(point.district_code).district
        if district is not None:
            by_district.setdefault(district.code, set()).add(point.year_gregorian)
    if len(by_district) < _MIN_MAP_REGIONS:
        return None
    common = set.intersection(*by_district.values())
    return max(common) if common else None


def _wants_map(question: str) -> bool:
    """Require explicit spatial intent before adding a second spatial view."""

    return bool(
        re.search(
            r"\b(map|spatial|geographic|across districts|by district|where|khu vực|quận)\b"
            r"|ở đâu"
            r"|地圖|行政區|各區|哪裡|哪裏",
            question,
            re.IGNORECASE,
        )
    )


def _choropleth(
    *,
    visualization_id: str,
    title: str,
    labels: dict[str, str],
    language: NameLanguage,
    value_label: str,
    unit: str | None,
    readings: Sequence[MapReading],
    citation_ids: tuple[str, ...],
    description: str | None = None,
) -> VisualizationSpec | None:
    """Build a district-keyed map spec, or None when nothing maps.

    The spec carries values keyed by canonical district code and names the
    boundary scheme; it never carries geometry. A renderer joins these rows to
    whichever boundary file it holds for that scheme. Entities that do not
    resolve to a New Taipei district are dropped rather than guessed at: the
    limitation block reports them, because placing them would require a spatial
    join this system does not perform.
    """

    rows: list[dict[str, VisualizationValue]] = []
    seen: set[str] = set()
    for reading in readings:
        district = resolve_district_name(reading.entity_id).district
        if district is None or reading.value is None or district.code in seen:
            continue
        seen.add(district.code)
        name = localized_district_name(district.code, language) or district.name
        rows.append(
            {
                "district_code": district.code,
                "district_name": name,
                "entity_id": reading.entity_id,
                "entity_name": readable_entity_name(
                    reading.entity_id, reading.entity_name, language
                ),
                "value": reading.value,
                "rank": reading.rank,
                "period": reading.period,
            }
        )
    if len(rows) < _MIN_MAP_REGIONS or len({row["value"] for row in rows}) < _MIN_BAR_CATEGORIES:
        return None
    rows.sort(key=lambda row: str(row["district_code"]))
    return VisualizationSpec(
        visualization_id=visualization_id,
        type=VisualizationType.CHOROPLETH,
        title=title,
        description=description,
        x=_encoding("district_code", labels["district"], "nominal"),
        y=_encoding("value", value_label, "quantitative", unit),
        region_field="district_code",
        region_scheme=RegionScheme.NEW_TAIPEI_DISTRICT,
        columns=(
            _column("district_code", labels["district_code"]),
            _column("district_name", labels["district"]),
            _column("value", value_label, unit),
        ),
        rows=tuple(rows[:_MAX_CHART_ROWS]),
        citation_ids=citation_ids,
        truncated=len(rows) > _MAX_CHART_ROWS,
    )


def _encoding(
    field: str,
    label: str,
    data_type: str,
    unit: str | None = None,
) -> VisualizationEncoding:
    return VisualizationEncoding.model_validate(
        {"field": field, "label": label, "data_type": data_type, "unit": unit}
    )


def _column(field: str, label: str, unit: str | None = None) -> VisualizationColumn:
    return VisualizationColumn(field=field, label=label, unit=unit)


def _language(question: str) -> NameLanguage:
    """Name places in the script the question was asked in."""

    return question_language(question)


def _labels(question: str) -> dict[str, str]:
    if question_language(question) is NameLanguage.ZH_HANT:
        return {
            "absolute_change": "絕對變化",
            "candidate": "候選地點",
            "comparison_title": "地區變化比較",
            "contribution_title": "第一名候選地點的評分貢獻",
            "coverage_title": "資料集涵蓋範圍",
            "dataset": "資料集",
            "district": "行政區",
            "district_code": "區代碼",
            "eligible": "符合條件",
            "entity": "地區",
            "entity_count": "地區數量",
            "feature": "特徵",
            "forecast_description": "預測值及其不確定性上下界",
            "forecast_suffix": "預測",
            "forecast_table_title": "預測資料表",
            "forecast_value": "預測值",
            "lower": "下界",
            "map_description": "以行政區為單位的分級著色圖。顏色代表後端回傳的數值本身",
            "metric": "指標",
            "model_version": "模型版本",
            "period": "期間",
            "period_end": "結束期間",
            "period_start": "開始期間",
            "points": "貢獻分數",
            "quality": "品質分數",
            "rank": "名次",
            "ranking_map_title": "候選地點排名地圖",
            "ranking_table_title": "候選地點排名表",
            "ranking_title": "候選地點排名",
            "score": "分數",
            "source": "資料來源",
            "trend_suffix": "趨勢",
            "upper": "上界",
            "value": "數值",
        }
    return {
        "absolute_change": "Absolute change",
        "candidate": "Candidate",
        "comparison_title": "Change by entity",
        "contribution_title": "Top candidate score contributions",
        "coverage_title": "Dataset coverage",
        "dataset": "Dataset",
        "district": "District",
        "district_code": "District code",
        "eligible": "Eligible",
        "entity": "Entity",
        "entity_count": "Entity count",
        "feature": "Feature",
        "forecast_description": "Point forecasts with lower and upper uncertainty bounds",
        "forecast_suffix": "forecast",
        "forecast_table_title": "Forecast data",
        "forecast_value": "Forecast value",
        "lower": "Lower bound",
        "map_description": "District choropleth; shading encodes the value the backend returned",
        "metric": "Metric",
        "model_version": "Model version",
        "period": "Period",
        "period_end": "Period end",
        "period_start": "Period start",
        "points": "Contribution points",
        "quality": "Quality score",
        "rank": "Rank",
        "ranking_map_title": "Candidate ranking map",
        "ranking_table_title": "Candidate ranking table",
        "ranking_title": "Candidate ranking",
        "score": "Score",
        "source": "Source",
        "trend_suffix": "trend",
        "upper": "Upper bound",
        "value": "Value",
    }
