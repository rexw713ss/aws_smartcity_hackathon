"""Deterministic visualization specs built from grounded agent results."""

import re

from youth_compass.agent.contracts import (
    CandidateInsight,
    DatasetInspection,
    EntityComparison,
    ObservationSeries,
    VisualizationColumn,
    VisualizationEncoding,
    VisualizationSpec,
    VisualizationType,
    VisualizationValue,
)
from youth_compass.ports import ForecastResult, SourceCandidate

_MAX_CHART_ROWS = 200
_MAX_TABLE_ROWS = 200


class VisualizationBuilder:
    """Map typed results to a small frontend-independent template allowlist."""

    def decision(
        self,
        question: str,
        candidates: tuple[CandidateInsight, ...],
        citation_ids: tuple[str, ...],
    ) -> tuple[VisualizationSpec, ...]:
        labels = _labels(question)
        ranked_rows: list[dict[str, VisualizationValue]] = [
            {
                "rank": candidate.rank,
                "entity_id": candidate.entity_id,
                "entity_name": candidate.entity_name or candidate.entity_id,
                "score": candidate.score,
                "eligible": candidate.eligible,
            }
            for candidate in candidates
        ]
        eligible_rows = [row for row in ranked_rows if row["eligible"] and row["score"] is not None]
        specs: list[VisualizationSpec] = []
        if eligible_rows:
            specs.append(
                VisualizationSpec(
                    visualization_id="candidate-ranking",
                    type=VisualizationType.RANKING_BAR,
                    title=labels["ranking_title"],
                    x=_encoding("score", labels["score"], "quantitative", "score_0_100"),
                    y=_encoding("entity_name", labels["candidate"], "nominal"),
                    rows=tuple(eligible_rows[:_MAX_CHART_ROWS]),
                    citation_ids=citation_ids,
                    truncated=len(eligible_rows) > _MAX_CHART_ROWS,
                )
            )
        top = next((candidate for candidate in candidates if candidate.rank == 1), None)
        if top is not None and top.contributions:
            contribution_rows: list[dict[str, VisualizationValue]] = [
                {
                    "feature_code": item.feature_code,
                    "raw_value": item.raw_value,
                    "effective_weight": item.effective_weight,
                    "points": item.points,
                }
                for item in top.contributions
            ]
            specs.append(
                VisualizationSpec(
                    visualization_id="top-candidate-contributions",
                    type=VisualizationType.CONTRIBUTION_BAR,
                    title=labels["contribution_title"],
                    x=_encoding("points", labels["points"], "quantitative", "score_points"),
                    y=_encoding("feature_code", labels["feature"], "nominal"),
                    rows=tuple(contribution_rows[:_MAX_CHART_ROWS]),
                    citation_ids=citation_ids,
                    truncated=len(contribution_rows) > _MAX_CHART_ROWS,
                )
            )
        if ranked_rows:
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
        return tuple(specs)

    def observations(
        self,
        question: str,
        series: ObservationSeries,
        comparison: EntityComparison | None,
        citation_ids: tuple[str, ...],
    ) -> tuple[VisualizationSpec, ...]:
        labels = _labels(question)
        rows: list[dict[str, VisualizationValue]] = [
            {
                "period": point.period,
                "entity_id": point.entity_id,
                "entity_name": point.entity_name or point.entity_id,
                "value": point.value,
                "estimated_value": point.estimated_value,
            }
            for point in series.points
        ]
        metric_title = f"{series.metric_code} {labels['trend_suffix']}"
        specs = [
            VisualizationSpec(
                visualization_id="observation-trend",
                type=VisualizationType.LINE,
                title=metric_title,
                x=_encoding("period", labels["period"], "temporal"),
                y=_encoding("value", labels["value"], "quantitative", series.unit_code),
                series_field="entity_name",
                rows=tuple(rows[:_MAX_CHART_ROWS]),
                citation_ids=citation_ids,
                truncated=len(rows) > _MAX_CHART_ROWS,
            )
        ]
        if comparison is not None:
            changes: list[dict[str, VisualizationValue]] = [
                {
                    "entity_id": change.entity_id,
                    "entity_name": change.entity_name or change.entity_id,
                    "absolute_change": change.absolute_change,
                    "percent_change": change.percent_change,
                    "direction": change.direction,
                }
                for change in comparison.changes
            ]
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
                    rows=tuple(changes[:_MAX_CHART_ROWS]),
                    citation_ids=citation_ids,
                    truncated=len(changes) > _MAX_CHART_ROWS,
                )
            )
        specs.append(
            VisualizationSpec(
                visualization_id="observation-table",
                type=VisualizationType.DATA_TABLE,
                title=labels["observation_table_title"],
                columns=(
                    _column("period", labels["period"]),
                    _column("entity_name", labels["entity"]),
                    _column("value", labels["value"], series.unit_code),
                    _column("estimated_value", labels["estimated_value"], series.unit_code),
                ),
                rows=tuple(rows[:_MAX_TABLE_ROWS]),
                citation_ids=citation_ids,
                truncated=len(rows) > _MAX_TABLE_ROWS,
            )
        )
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
                    _column("metric_code", labels["metric"]),
                    _column("period_start", labels["period_start"]),
                    _column("period_end", labels["period_end"]),
                    _column("entity_count", labels["entity_count"]),
                    _column("quality_score", labels["quality"]),
                ),
                rows=(
                    {
                        "dataset_id": inspection.dataset_id,
                        "metric_code": inspection.metric_code,
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
        rows: list[dict[str, VisualizationValue]] = [
            {
                "period": str(point.year_gregorian),
                "entity_id": point.district_code,
                "entity_name": point.district_code,
                "value": point.value,
                "lower": point.lower,
                "upper": point.upper,
                "model_version": result.model_version,
            }
            for point in result.points
        ]
        return (
            VisualizationSpec(
                visualization_id="forecast-trend",
                type=VisualizationType.LINE,
                title=f"{result.metric_code} {labels['forecast_suffix']}",
                description=labels["forecast_description"],
                x=_encoding("period", labels["period"], "temporal"),
                y=_encoding("value", labels["forecast_value"], "quantitative"),
                series_field="entity_name",
                rows=tuple(rows[:_MAX_CHART_ROWS]),
                citation_ids=citation_ids,
                truncated=len(rows) > _MAX_CHART_ROWS,
            ),
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
            ),
        )

    def sources(
        self, question: str, candidates: tuple[SourceCandidate, ...]
    ) -> tuple[VisualizationSpec, ...]:
        if not candidates:
            return ()
        labels = _labels(question)
        rows: list[dict[str, VisualizationValue]] = [
            {
                "candidate_id": item.candidate_id,
                "title": item.title,
                "publisher": item.publisher,
                "source_format": item.source_format.value,
                "license": item.license,
                "period_start": item.period_start,
                "period_end": item.period_end,
            }
            for item in candidates
        ]
        return (
            VisualizationSpec(
                visualization_id="source-candidates-table",
                type=VisualizationType.DATA_TABLE,
                title=labels["source_title"],
                columns=(
                    _column("candidate_id", labels["source_id"]),
                    _column("title", labels["source"]),
                    _column("publisher", labels["publisher"]),
                    _column("source_format", labels["format"]),
                    _column("license", labels["license"]),
                    _column("period_start", labels["period_start"]),
                    _column("period_end", labels["period_end"]),
                ),
                rows=tuple(rows),
            ),
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


def _labels(question: str) -> dict[str, str]:
    if re.search(r"[\u3400-\u9fff]", question):
        return {
            "absolute_change": "絕對變化",
            "candidate": "候選地點",
            "comparison_title": "地區變化比較",
            "contribution_title": "第一名候選地點的評分貢獻",
            "coverage_title": "資料集涵蓋範圍",
            "dataset": "資料集",
            "eligible": "符合條件",
            "entity": "地區",
            "entity_count": "地區數量",
            "estimated_value": "估算值",
            "feature": "特徵",
            "format": "格式",
            "forecast_description": "預測值及其不確定性上下界",
            "forecast_suffix": "預測",
            "forecast_table_title": "預測資料表",
            "forecast_value": "預測值",
            "license": "授權條款",
            "lower": "下界",
            "metric": "指標",
            "model_version": "模型版本",
            "observation_table_title": "觀測資料表",
            "period": "期間",
            "period_end": "結束期間",
            "period_start": "開始期間",
            "points": "貢獻分數",
            "publisher": "發布單位",
            "quality": "品質分數",
            "rank": "名次",
            "ranking_table_title": "候選地點排名表",
            "ranking_title": "候選地點排名",
            "score": "分數",
            "source": "資料來源",
            "source_id": "來源識別碼",
            "source_title": "可用的外部資料來源",
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
        "eligible": "Eligible",
        "entity": "Entity",
        "entity_count": "Entity count",
        "estimated_value": "Estimated value",
        "feature": "Feature",
        "format": "Format",
        "forecast_description": "Point forecasts with lower and upper uncertainty bounds",
        "forecast_suffix": "forecast",
        "forecast_table_title": "Forecast data",
        "forecast_value": "Forecast value",
        "license": "License",
        "lower": "Lower bound",
        "metric": "Metric",
        "model_version": "Model version",
        "observation_table_title": "Observation data",
        "period": "Period",
        "period_end": "Period end",
        "period_start": "Period start",
        "points": "Contribution points",
        "publisher": "Publisher",
        "quality": "Quality score",
        "rank": "Rank",
        "ranking_table_title": "Candidate ranking table",
        "ranking_title": "Candidate ranking",
        "score": "Score",
        "source": "Source",
        "source_id": "Source ID",
        "source_title": "Available external data sources",
        "trend_suffix": "trend",
        "upper": "Upper bound",
        "value": "Value",
    }
