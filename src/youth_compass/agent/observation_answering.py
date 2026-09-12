"""The observation pipeline: catalog, single-dataset reads, and forecasts.

Everything here answers from published observations rather than from a decision
profile. One entry point routes between three shapes of question — what data
exists, what the data says, and what a published model projects — because they
share the same retrieval, the same citation rules, and the same refusal path
when nothing usable is published.

Multi-dataset questions are handed to `youth_compass.agent.multi_dataset`, which
owns the join.
"""

import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from youth_compass.agent.contracts import (
    AnalysisFilters,
    AnalysisOperation,
    AnswerCompositionContext,
    CopilotResponse,
    DatasetInspection,
    DecomposedQuery,
    EntityComparison,
    EvidenceCitation,
    ObservationSeries,
    RoutedToolPlan,
    ToolTrace,
    VisualizationColumn,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.data_shape import profile_series
from youth_compass.agent.measures import choose_measure
from youth_compass.agent.multi_dataset import (
    answer_multi_dataset_observations,
    explicit_catalog_datasets,
)
from youth_compass.agent.observation_tools import ObservationToolSuite
from youth_compass.agent.support import (
    AnswerSupport,
    answered,
    citation_from_series,
    grounded_json,
    name_language,
    response_language_for_fallback,
    unavailable_trace,
)
from youth_compass.agent.viz_selection import select_visualizations
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import QueryExecutionError, YouthCompassError
from youth_compass.ontology import (
    humanize_code,
    readable_entity_name,
    resolve_district_name,
)
from youth_compass.ports import ForecastRequest, ForecastResult, ForecastService


class ObservationAnswering:
    """Answer observation, catalog, and forecast questions from one suite."""

    def __init__(
        self,
        *,
        tools: ObservationToolSuite,
        support: AnswerSupport,
        forecast_service: ForecastService | None = None,
    ) -> None:
        self._tools = tools
        self._support = support
        self._forecast = forecast_service

    async def answer(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        min_quality_score: float,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        """Answer from published observations, or say why none can be used."""

        tools = self._tools
        # A place typed as Tamsui, 淡水區, or Đạm Thủy names district 12. The
        # scope itself is left untouched: the tools below match on canonical
        # identity, so the reader keeps seeing the identifier they supplied.
        recognized = _recognized_places(decomposition.entity_ids)
        if recognized:
            trace.append(
                ToolTrace(
                    tool="resolve_local_ontology",
                    outcome="ok",
                    summary="recognized place names: " + "; ".join(recognized),
                )
            )
        # Catalog questions are inventory questions, not requests to select one
        # arbitrary dataset. Returning one matching record made the assistant
        # look as though that was the entire catalog and exposed an internal
        # immutable version identifier in the prose.
        if (
            AnalysisOperation.QUERY_OBSERVATIONS not in decomposition.operations
            and AnalysisOperation.FORECAST_METRIC not in decomposition.operations
        ):
            return self._answer_catalog(
                now,
                decomposition,
                routed_plan,
                trace,
                min_quality_score=min_quality_score,
            )

        requested_datasets = explicit_catalog_datasets(
            decomposition.original_question,
            tools.catalog.list_datasets(),
        )
        if len(requested_datasets) > 1:
            return answer_multi_dataset_observations(
                now,
                decomposition,
                routed_plan,
                trace,
                requested_datasets,
                tools=tools,
                support=self._support,
                min_quality_score=min_quality_score,
            )
        try:
            inspection = tools.inspect_dataset.execute(
                decomposition, min_quality_score=min_quality_score
            )
            metadata = tools.catalog.get(inspection.dataset_id)
            if metadata.version != inspection.dataset_version:
                raise QueryExecutionError("the published dataset version changed during analysis")
        except YouthCompassError as exc:
            trace.append(unavailable_trace("inspect_dataset", exc))
            return self._support.observation_failure(
                now, decomposition, routed_plan, trace, warning=str(exc)
            )
        trace.extend(
            (
                ToolTrace(
                    tool="search_catalog",
                    outcome="ok",
                    summary=f"selected {inspection.dataset_id}@{inspection.dataset_version}",
                ),
                ToolTrace(
                    tool="inspect_dataset",
                    outcome="ok",
                    summary=(
                        f"resolved {inspection.metric_code} across "
                        f"{inspection.period_start} to {inspection.period_end}"
                    ),
                ),
            )
        )
        if AnalysisOperation.FORECAST_METRIC in decomposition.operations:
            return await self._answer_forecast(
                now,
                decomposition,
                routed_plan,
                trace,
                inspection,
                metadata,
                on_text=on_text,
            )
        if AnalysisOperation.QUERY_OBSERVATIONS not in decomposition.operations:
            fallback_answer = (
                f"{humanize_code(inspection.dataset_id)}@{inspection.dataset_version} contains "
                f"{humanize_code(inspection.metric_code)} from {inspection.period_start} to "
                f"{inspection.period_end} across {inspection.entity_count} entities."
            )
            answer = await self._support.compose(
                AnswerCompositionContext(
                    question=decomposition.original_question,
                    analysis_type="dataset_inspection",
                    grounded_facts_json=grounded_json(inspection.model_dump(mode="json")),
                    fallback_answer=fallback_answer,
                ),
                trace,
                on_text=on_text,
            )
            visualizations = self._support.visualizations.inspection(
                decomposition.original_question, inspection
            )
            self._support.trace_visualizations(trace, visualizations)
            return answered(
                answer=answer,
                now=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                trace=trace,
                dataset_inspection=inspection,
                visualizations=visualizations,
            )
        try:
            series = tools.query_observations.execute(decomposition, inspection, metadata)
        except YouthCompassError as exc:
            trace.append(unavailable_trace("query_observations", exc))
            return self._support.observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning=str(exc),
                inspection=inspection,
            )
        series = _readable_observation_series(series, decomposition.original_question)
        scope = _filter_scope(decomposition.filters)
        trace.append(
            ToolTrace(
                tool="query_observations",
                outcome="ok",
                summary=(
                    f"retrieved {len(series.points)} aggregated observations"
                    + (f" within {scope}" if scope else "")
                ),
            )
        )
        comparison = None
        if AnalysisOperation.COMPARE_ENTITIES in decomposition.operations:
            try:
                comparison = tools.compare_entities.execute(series)
            except YouthCompassError as exc:
                trace.append(unavailable_trace("compare_entities", exc))
                return self._support.observation_failure(
                    now,
                    decomposition,
                    routed_plan,
                    trace,
                    warning=str(exc),
                    inspection=inspection,
                    series=series,
                )
            trace.append(
                ToolTrace(
                    tool="compare_entities",
                    outcome="ok",
                    summary=f"calculated changes for {len(comparison.changes)} entities",
                )
            )
        citation = citation_from_series("data-1", metadata, series, decomposition.original_question)
        if AnalysisOperation.EXPLAIN_LINEAGE in decomposition.operations:
            trace.append(
                ToolTrace(
                    tool="explain_lineage",
                    outcome="ok",
                    summary="attached 1 dataset-version citation",
                )
            )
        fallback_answer = _observation_answer(
            series,
            comparison,
            scope,
            question=decomposition.original_question,
            citation_id=citation.citation_id,
        )
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="observation_comparison",
                grounded_facts_json=grounded_json(
                    {
                        "dataset_inspection": inspection.model_dump(mode="json"),
                        "observation_series": series.model_dump(mode="json"),
                        "comparison": (comparison.model_dump(mode="json") if comparison else None),
                        "citation": citation.model_dump(mode="json"),
                        "applied_filters": decomposition.filters.model_dump(mode="json"),
                    }
                ),
                allowed_citation_ids=(citation.citation_id,),
                fallback_answer=fallback_answer,
            ),
            trace,
            on_text=on_text,
        )
        # Doc 30: look at the retrieved rows before deciding what to draw, pick
        # the unit that makes the comparison legible, then let scoring decide
        # which of the defensible views actually reach the answer.
        profile = profile_series(series)
        measure = choose_measure(
            profile, decomposition, language=name_language(decomposition.original_question)
        )
        selection = select_visualizations(
            self._support.visualizations.observation_candidates(
                decomposition.original_question,
                series,
                comparison,
                (citation.citation_id,),
                decomposition=decomposition,
                measure=measure,
            ),
            profile=profile,
        )
        visualizations = selection.selected
        self._support.trace_visualizations(trace, visualizations, selection.rejected)
        limitations = self._support.limitations.build(
            now=now,
            citations=(citation,),
            observed_entity_ids=[point.entity_id for point in series.points],
            requested_entity_ids=decomposition.entity_ids,
            catalog_terms=_catalog_terms(inspection, metadata),
            series=series,
        )
        self._support.trace_limitations(trace, limitations)
        return answered(
            answer=answer,
            now=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            trace=trace,
            dataset_inspection=inspection,
            observation_series=series,
            comparison=comparison,
            citations=(citation,),
            assumptions=(
                "Canonical rows sharing an entity, period, metric, unit, and scope are summed.",
                "Changes compare the first and last observations in the requested period.",
            ),
            # A defect in the retrieved rows is the reader's business, not just
            # the chart selector's: it is what decides whether the numbers above
            # can be read at face value.
            warnings=tuple(issue.message for issue in profile.issues),
            visualizations=visualizations,
            limitations=limitations,
        )

    def _answer_catalog(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        min_quality_score: float,
    ) -> CopilotResponse:
        """List every usable catalog entry without leaking version IDs in prose."""

        tools = self._tools
        records = tuple(
            sorted(
                (
                    item
                    for item in tools.catalog.list_datasets()
                    if item.status is DatasetStatus.PUBLISHED
                    and item.quality_score >= min_quality_score
                ),
                key=lambda item: item.dataset_id,
            )
        )
        if not records:
            trace.append(
                ToolTrace(
                    tool="search_catalog",
                    outcome="unavailable",
                    summary="no published dataset satisfies the requested quality",
                )
            )
            return self._support.observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning="no published dataset satisfies the requested quality",
            )

        trace.append(
            ToolTrace(
                tool="search_catalog",
                outcome="ok",
                summary=f"listed {len(records)} published dataset(s)",
            )
        )
        citations = tuple(
            EvidenceCitation(
                citation_id=f"data-{index}",
                dataset_id=item.dataset_id,
                dataset_version=item.version,
                quality_score=item.quality_score,
                retrieved_at=item.published_at or item.created_at,
            )
            for index, item in enumerate(records, start=1)
        )
        bullets: list[str] = []
        for item, citation in zip(records, citations, strict=True):
            name = humanize_code(item.dataset_id)
            topic = humanize_code(item.topic)
            topic_detail = f"topic: {topic}; " if topic.casefold() != name.casefold() else ""
            bullets.append(
                f"- {name} — {topic_detail}quality {item.quality_score:.0%}; breakdowns: "
                f"{', '.join(humanize_code(field) for field in item.grain.dimensions)} "
                f"[{citation.citation_id}]"
            )
        answer = (
            f"{len(records)} published dataset{'s are' if len(records) != 1 else ' is'} "
            "available for questions:\n\n"
            + "\n".join(bullets)
            + "\n\nTry asking for a trend, comparison, district, or time period shown by the data."
        )
        visualizations = (
            VisualizationSpec(
                visualization_id="published-dataset-catalog",
                type=VisualizationType.DATA_TABLE,
                title="Published datasets you can ask about",
                columns=(
                    VisualizationColumn(field="dataset", label="Dataset"),
                    VisualizationColumn(field="topic", label="Topic"),
                    VisualizationColumn(field="grain", label="Available breakdowns"),
                    VisualizationColumn(field="quality", label="Quality"),
                ),
                rows=tuple(
                    {
                        "dataset": humanize_code(item.dataset_id),
                        "topic": humanize_code(item.topic),
                        "grain": ", ".join(humanize_code(field) for field in item.grain.dimensions),
                        "quality": round(item.quality_score * 100, 1),
                    }
                    for item in records
                ),
                citation_ids=tuple(item.citation_id for item in citations),
            ),
        )
        self._support.trace_visualizations(trace, visualizations)
        return answered(
            answer=answer,
            now=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            trace=trace,
            citations=citations,
            visualizations=visualizations,
        )

    async def _answer_forecast(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        inspection: DatasetInspection,
        metadata: DatasetMetadata,
        *,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        service = self._forecast
        if service is None:  # Defensive: routed only when a forecast service exists.
            raise RuntimeError("forecast service is unavailable")
        try:
            result = service.get_forecast(
                ForecastRequest(
                    metric_code=inspection.metric_code,
                    district_codes=list(decomposition.entity_ids),
                    horizon_years=_forecast_horizon(decomposition.time_expression, now.year),
                    as_of=now.date(),
                )
            )
        except YouthCompassError as exc:
            trace.append(unavailable_trace("forecast_metric", exc))
            return self._support.observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning=str(exc),
                inspection=inspection,
            )
        trace.append(
            ToolTrace(
                tool="forecast_metric",
                outcome="ok",
                summary=(f"retrieved {len(result.points)} points from {result.model_version}"),
            )
        )
        citation = EvidenceCitation(
            citation_id="data-1",
            dataset_id=inspection.dataset_id,
            dataset_version=inspection.dataset_version,
            quality_score=inspection.quality_score,
            retrieved_at=metadata.published_at or metadata.created_at,
        )
        if AnalysisOperation.EXPLAIN_LINEAGE in decomposition.operations:
            trace.append(
                ToolTrace(
                    tool="explain_lineage",
                    outcome="ok",
                    summary=(f"attached input dataset citation and model {result.model_version}"),
                )
            )
        fallback_answer = _forecast_answer(result)
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="forecast",
                grounded_facts_json=grounded_json(
                    {
                        "dataset_inspection": inspection.model_dump(mode="json"),
                        "forecast": result.model_dump(mode="json"),
                        "citation": citation.model_dump(mode="json"),
                    }
                ),
                allowed_citation_ids=(citation.citation_id,),
                fallback_answer=fallback_answer,
            ),
            trace,
            on_text=on_text,
        )
        visualizations = self._support.visualizations.forecast(
            decomposition.original_question,
            result,
            (citation.citation_id,),
        )
        self._support.trace_visualizations(trace, visualizations)
        limitations = self._support.limitations.build(
            now=now,
            citations=(citation,),
            observed_entity_ids=[point.district_code for point in result.points],
            requested_entity_ids=decomposition.entity_ids,
            catalog_terms=_catalog_terms(inspection, metadata),
        )
        self._support.trace_limitations(trace, limitations)
        return answered(
            answer=answer,
            now=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            trace=trace,
            dataset_inspection=inspection,
            forecast_result=result,
            citations=(citation,),
            assumptions=(
                "Forecast points come from the latest published model available as of the request.",
                "Intervals describe model uncertainty and are not guaranteed outcomes.",
            ),
            warnings=("The forecast is predictive, not evidence of policy causation.",),
            visualizations=visualizations,
            limitations=limitations,
        )


def _recognized_places(entity_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Name the districts behind the requested identifiers, for the trace.

    Only spellings that are not already the canonical code are reported: a
    caller that asked for "12" learns nothing from being told it means 12.
    """

    recognized: list[str] = []
    for entity_id in entity_ids:
        district = resolve_district_name(entity_id).district
        if district is not None and district.code != entity_id:
            recognized.append(f"{entity_id} = {district.code} {district.name}")
    return tuple(recognized)


def _catalog_terms(inspection: DatasetInspection, metadata: DatasetMetadata) -> tuple[str, ...]:
    """Collect the catalog text that may name a population's definitional basis."""

    return (
        inspection.topic,
        inspection.dataset_id,
        inspection.metric_code,
        metadata.source_uri,
    )


def _filter_scope(filters: AnalysisFilters) -> str | None:
    """Describe applied filters so the narrative never hides a narrowed scope."""

    parts: list[str] = []
    if filters.age_lower is not None and filters.age_upper is not None:
        parts.append(f"ages {filters.age_lower} to {filters.age_upper}")
    elif filters.age_lower is not None:
        parts.append(f"ages {filters.age_lower} and above")
    elif filters.age_upper is not None:
        parts.append(f"ages up to {filters.age_upper}")
    if filters.gender_code is not None:
        parts.append(filters.gender_code)
    return ", ".join(parts) if parts else None


def _readable_observation_series(series: ObservationSeries, question: str) -> ObservationSeries:
    """Repair source-supplied entity labels before they enter any public surface."""

    language = name_language(question)
    return series.model_copy(
        update={
            "points": tuple(
                point.model_copy(
                    update={
                        "entity_name": readable_entity_name(
                            point.entity_id, point.entity_name, language
                        )
                    }
                )
                for point in series.points
            )
        }
    )


def _observation_answer(
    series: ObservationSeries,
    comparison: EntityComparison | None,
    filter_scope: str | None = None,
    *,
    question: str = "",
    citation_id: str = "data-1",
) -> str:
    """Build a natural grounded narrative that remains useful if the model fails."""

    language = response_language_for_fallback(question)
    metric = humanize_code(series.metric_code)
    subject = (
        "youth population"
        if series.metric_code == "population_count" and series.population_scope == "youth_specific"
        else metric.casefold()
    )
    scope = f" for {filter_scope}" if filter_scope else ""
    if comparison is None:
        if language == "vi":
            return (
                f"{metric}\n\nĐã tìm thấy {len(series.points)} quan sát đã công bố"
                f"{scope}. [{citation_id}]"
            )
        if language == "zh":
            return f"{metric}\n\n共取得{len(series.points)}筆已發布觀測值。[{citation_id}]"
        return (
            f"{metric}\n\nRetrieved {len(series.points)} published observations"
            f"{scope}. [{citation_id}]"
        )
    changes = comparison.changes[:8]
    if len(changes) == 1:
        change = changes[0]
        name = readable_entity_name(change.entity_id, change.entity_name, name_language(question))
        first = f"{change.first_value:,.0f}"
        last = f"{change.last_value:,.0f}"
        percent = abs(change.percent_change) if change.percent_change is not None else None
        if language == "vi":
            amount = f", tương đương {percent:.2f}%" if percent is not None else ""
            if change.direction == "decreased":
                movement = f"giảm từ {first} người vào {change.first_period} xuống {last} người"
                end_period = f" vào {change.last_period}"
            elif change.direction == "increased":
                movement = f"tăng từ {first} người vào {change.first_period} lên {last} người"
                end_period = f" vào {change.last_period}"
            else:
                movement = (
                    f"giữ nguyên ở mức {first} người từ {change.first_period} "
                    f"đến {change.last_period}"
                )
                end_period = ""
            answer = (
                f"Dân số thanh niên tại {name} đã {movement}{end_period}{amount}. [{citation_id}]"
            )
        elif language == "zh":
            movement = {"decreased": "下降", "increased": "上升"}.get(change.direction, "維持不變")
            amount = f"，變動幅度為{percent:.2f}%" if percent is not None else ""  # noqa: RUF001
            answer = (
                f"{name}的青年人口從{change.first_period}的{first}人{movement}至"
                f"{change.last_period}的{last}人{amount}。[{citation_id}]"
            )
        else:
            if change.direction == "decreased":
                movement, noun = "fell", "decline"
                statement = (
                    f"{movement} from {first} in {change.first_period} to "
                    f"{last} in {change.last_period}"
                )
            elif change.direction == "increased":
                movement, noun = "rose", "increase"
                statement = (
                    f"{movement} from {first} in {change.first_period} to "
                    f"{last} in {change.last_period}"
                )
            else:
                noun = "change"
                statement = (
                    f"remained unchanged at {first} from {change.first_period} "
                    f"to {change.last_period}"
                )
            article = "an" if noun == "increase" else "a"
            amount = f"—{article} {noun} of {percent:.2f}%" if percent is not None else ""
            answer = f"{name}'s {subject} {statement}{amount}. [{citation_id}]"
        if filter_scope:
            answer += f" The figures cover {filter_scope}."
        return answer

    bullets: list[str] = []
    for change in changes:
        name = readable_entity_name(change.entity_id, change.entity_name, name_language(question))
        delta = (
            f"{change.percent_change:+.2f}%"
            if change.percent_change is not None
            else f"{change.absolute_change:+g} {series.unit_code}"
        )
        bullets.append(
            f"- {name}: {change.first_value:,.0f} → {change.last_value:,.0f} "
            f"({delta}) [{citation_id}]"
        )
    declined = sum(change.direction == "decreased" for change in changes)
    increased = sum(change.direction == "increased" for change in changes)
    if language == "vi":
        summary = (
            f"{declined}/{len(changes)} địa điểm giảm và {increased}/{len(changes)} địa điểm tăng."
        )
        heading = f"Nhìn chung, xu hướng giữa các địa điểm không hoàn toàn giống nhau: {summary}"
    elif language == "zh":
        summary = f"{len(changes)}個地區中，{declined}個下降、{increased}個上升。"  # noqa: RUF001
        heading = f"整體來看，各地區的趨勢並不完全相同：{summary}"  # noqa: RUF001
    else:
        summary = f"{declined} of {len(changes)} locations decreased; {increased} increased."
        heading = f"The trend varies across locations: {summary}"
    scope_note = f" The figures cover {filter_scope}." if filter_scope else ""
    return f"{heading}{scope_note}\n\n" + "\n".join(bullets)


def _forecast_horizon(time_expression: str | None, current_year: int) -> int:
    if time_expression is None:
        return 3
    count = re.search(r"(\d+)\s*(?:years?|năm|年)", time_expression)
    if count:
        return max(1, min(20, int(count.group(1))))
    years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", time_expression)]
    if years:
        return max(1, min(20, max(years) - current_year))
    return 3


def _forecast_answer(result: ForecastResult) -> str:
    first = result.points[0]
    last = result.points[-1]
    return (
        f"Model {result.model_version} forecasts {humanize_code(result.metric_code)} from "
        f"{first.year_gregorian} to {last.year_gregorian}. The final point estimate is "
        f"{last.value:g}, with an uncertainty interval from {last.lower:g} to "
        f"{last.upper:g}."
    )
