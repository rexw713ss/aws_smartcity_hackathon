"""The observation pipeline: catalog, single-dataset reads, and forecasts.

Everything here answers from published observations rather than from a decision
profile. One entry point routes between three shapes of question — what data
exists, what the data says, and what a published model projects — because they
share the same retrieval, the same citation rules, and the same refusal path
when nothing usable is published.

Multi-dataset questions are handed to `youth_compass.agent.multi_dataset`, which
owns the join.
"""

import asyncio
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
    QuestionFocus,
    RoutedToolPlan,
    RoutedToolStep,
    ToolTrace,
    VisualizationColumn,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.data_shape import EntitySignal, SeriesProfile, profile_series
from youth_compass.agent.execution import ExecutionState, PlanExecutor, StepHandler
from youth_compass.agent.grounding import inspection_digest, series_digest
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
    NameLanguage,
    humanize_code,
    readable_entity_name,
    resolve_district_name,
)
from youth_compass.ports import (
    ForecastAccuracy,
    ForecastEvaluation,
    ForecastRequest,
    ForecastResult,
    ForecastService,
)


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
        on_stage: Callable[[str], Awaitable[None]] | None = None,
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
        # Retrieval runs the routed plan rather than a parallel `if` chain, so
        # the steps in `routed_plan.steps`, their declared dependencies, and the
        # trace entries below are one description of one execution.
        state = ExecutionState(decomposition=decomposition, min_quality_score=min_quality_score)
        executor = PlanExecutor(self._retrieval_handlers())
        retrieval = _retrieval_plan(routed_plan, executor)
        try:
            await executor.run(retrieval, state, trace)
        except YouthCompassError as exc:
            return self._support.observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning=str(exc),
                inspection=state.get("inspection"),
                series=state.get("series"),
            )
        if on_stage is not None:
            await on_stage("analysis")
        inspection = state.require("inspection")
        metadata = state.require("metadata")
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
                    grounded_facts_json=grounded_json(inspection_digest(inspection)),
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
        series = state.require("series")
        scope = _filter_scope(decomposition.filters)
        comparison = state.get("comparison")
        # A plan that omitted explain_lineage still gets a citation: an answer
        # carrying numbers without provenance is not publishable. What it does not
        # get is a lineage trace entry, because that step did not run.
        citation = state.get("citation") or citation_from_series(
            "data-1", metadata, series, decomposition.original_question
        )
        # Build the profile before the fallback narrative. Production may use
        # the deterministic composer when Bedrock is disabled or rejects a
        # draft; that path still needs to explain the result rather than merely
        # report how many rows were retrieved.
        profile = profile_series(series)
        fallback_answer = _observation_answer(
            series,
            comparison,
            scope,
            question=decomposition.original_question,
            citation_id=citation.citation_id,
            profile=profile,
        )
        # Doc 30: look at the retrieved rows before deciding what to draw, pick
        # the unit that makes the comparison legible, then let scoring decide
        # which of the defensible views actually reach the answer. The profile is
        # built here rather than after composing because the composer needs it:
        # it is the bounded description that replaced dumping every row.
        if profile.monthly_coverage_ratio is not None:
            trace.append(
                ToolTrace(
                    tool="inspect_temporal_coverage",
                    outcome=("missing_detected" if profile.missing_monthly_points else "complete"),
                    summary=(
                        f"found {profile.missing_monthly_points} missing of "
                        f"{profile.expected_monthly_points} expected monthly entity-points; "
                        f"selected a {profile.plot_interval_months}-month chart cadence"
                    ),
                )
            )
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="observation_comparison",
                # A digest, not a dump. 29 districts over 60 months is 1,740
                # points; the profile plus landmark points says what a narrative
                # can legitimately use, and keeps data-derived text quarantined.
                grounded_facts_json=grounded_json(
                    {
                        "dataset": inspection_digest(inspection),
                        "series": series_digest(series, profile, comparison),
                        "citation_id": citation.citation_id,
                        "applied_filters": decomposition.filters.model_dump(mode="json"),
                    }
                ),
                allowed_citation_ids=(citation.citation_id,),
                fallback_answer=fallback_answer,
            ),
            trace,
            on_text=on_text,
        )
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
                profile=profile,
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

    def _retrieval_handlers(self) -> dict[AnalysisOperation, StepHandler]:
        """One handler per retrieval operation the plan can route.

        Each is `async` and each pushes its blocking work onto a worker thread.
        The tools are synchronous and one of them is an Athena query: called
        directly from a coroutine it holds the event loop for the whole scan, so
        every other in-flight request waits behind a query it is not waiting for.
        """

        tools = self._tools

        async def search_catalog(state: ExecutionState, step: RoutedToolStep) -> str:
            del step
            metadata = await asyncio.to_thread(
                tools.inspect_dataset.select,
                state.decomposition,
                min_quality_score=state.min_quality_score,
            )
            state.put("metadata", metadata)
            return f"selected {metadata.dataset_id} from the published catalog"

        async def inspect_dataset(state: ExecutionState, step: RoutedToolStep) -> str:
            del step
            selected = state.require("metadata")
            inspection, scanned_bytes = await asyncio.to_thread(
                tools.inspect_dataset.execute_for_dataset_accounted,
                state.decomposition,
                selected.dataset_id,
                min_quality_score=state.min_quality_score,
            )
            # Re-read the catalog after inspecting: a version that changed under
            # the analysis would make the citation describe rows nobody queried.
            current = await asyncio.to_thread(tools.catalog.get, inspection.dataset_id)
            if current.version != inspection.dataset_version:
                raise QueryExecutionError("the published dataset version changed during analysis")
            state.put("metadata", current)
            state.put("inspection", inspection)
            state.charge(scanned_bytes=scanned_bytes)
            return (
                f"resolved {inspection.metric_code} across "
                f"{inspection.period_start} to {inspection.period_end}"
            )

        async def query_observations(state: ExecutionState, step: RoutedToolStep) -> str:
            del step
            inspection = state.require("inspection")
            metadata = state.require("metadata")
            series, scanned_bytes = await asyncio.to_thread(
                tools.query_observations.execute_accounted,
                state.decomposition,
                inspection,
                metadata,
            )
            series = _readable_observation_series(series, state.decomposition.original_question)
            state.put("series", series)
            state.charge(scanned_bytes=scanned_bytes)
            scope = _filter_scope(state.decomposition.filters)
            return f"retrieved {len(series.points)} aggregated observations" + (
                f" within {scope}" if scope else ""
            )

        async def compare_entities(state: ExecutionState, step: RoutedToolStep) -> str:
            del step
            comparison = await asyncio.to_thread(
                tools.compare_entities.execute, state.require("series")
            )
            state.put("comparison", comparison)
            return f"calculated changes for {len(comparison.changes)} entities"

        async def explain_lineage(state: ExecutionState, step: RoutedToolStep) -> str:
            del step
            citation = citation_from_series(
                "data-1",
                state.require("metadata"),
                state.require("series"),
                state.decomposition.original_question,
            )
            state.put("citation", citation)
            return "attached 1 dataset-version citation"

        return {
            AnalysisOperation.SEARCH_CATALOG: search_catalog,
            AnalysisOperation.INSPECT_DATASET: inspect_dataset,
            AnalysisOperation.QUERY_OBSERVATIONS: query_observations,
            AnalysisOperation.COMPARE_ENTITIES: compare_entities,
            AnalysisOperation.EXPLAIN_LINEAGE: explain_lineage,
        }

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

    async def _forecast_history(
        self,
        decomposition: DecomposedQuery,
        inspection: DatasetInspection,
        metadata: DatasetMetadata,
        result: ForecastResult,
        trace: list[ToolTrace],
    ) -> ObservationSeries | None:
        """Observed values for the forecast's snapshot month, to draw before it.

        Only a forecast that names its base period can be joined to history
        without guessing the month. A failed read leaves the forecast answer
        intact and is recorded, never hidden.
        """

        base = next((p.components for p in result.points if p.components is not None), None)
        if base is None:
            return None
        base_year, month = int(base.base_period[:4]), base.base_period[5:]
        scope = decomposition.model_copy(
            update={"time_expression": None, "filters": AnalysisFilters()}
        )
        try:
            series = await asyncio.to_thread(
                self._tools.query_observations.execute, scope, inspection, metadata
            )
        except YouthCompassError as exc:
            trace.append(unavailable_trace("query_observations", exc))
            return None
        points = tuple(
            point
            for point in series.points
            if point.period[5:] == month
            and base_year - _FORECAST_HISTORY_YEARS <= int(point.period[:4]) <= base_year
        )
        trace.append(
            ToolTrace(
                tool="query_observations",
                outcome="ok" if points else "empty",
                summary=f"retrieved {len(points)} observed month-{month} points before forecast",
            )
        )
        return series.model_copy(update={"points": points}) if points else None

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
        fallback_answer = (
            _forecast_accuracy_answer(result)
            if decomposition.focus is QuestionFocus.FORECAST_ACCURACY
            else None
        ) or _forecast_answer(result)
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="forecast",
                grounded_facts_json=grounded_json(
                    {
                        "dataset": inspection_digest(inspection),
                        "forecast": result.model_dump(mode="json"),
                        "citation_id": citation.citation_id,
                    }
                ),
                allowed_citation_ids=(citation.citation_id,),
                fallback_answer=fallback_answer,
            ),
            trace,
            on_text=on_text,
        )
        history = await self._forecast_history(decomposition, inspection, metadata, result, trace)
        visualizations = self._support.visualizations.forecast(
            decomposition.original_question,
            result,
            (citation.citation_id,),
            history,
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
            assumptions=_forecast_assumptions(result),
            warnings=_forecast_warnings(result),
            visualizations=visualizations,
            limitations=limitations,
        )


_FORECAST_HISTORY_YEARS = 5


def _retrieval_plan(plan: RoutedToolPlan, executor: PlanExecutor) -> RoutedToolPlan:
    """Narrow a routed plan to the retrieval steps this executor can run.

    A plan legitimately contains steps retrieval does not own — forecast_metric,
    simulate_scenario, web_search — which are handled by the branches after
    retrieval. Dropping them here would leave dangling ``depends_on`` references,
    so the surviving steps have their dependencies filtered to the steps that
    remain. The dependency edges between kept steps are preserved exactly, which
    is what the executor orders by.
    """

    runnable = tuple(step for step in plan.steps if executor.handles(step.operation))
    # Retrieval only owns lineage for an observation series. A forecast plan also
    # ends in explain_lineage, but the thing it cites is a model version and an
    # input dataset, which the forecast branch attaches itself. Running the
    # retrieval handler there would ask for a series nothing produced.
    queries_observations = any(
        step.operation is AnalysisOperation.QUERY_OBSERVATIONS for step in runnable
    )
    kept = tuple(
        step
        for step in runnable
        if queries_observations or step.operation is not AnalysisOperation.EXPLAIN_LINEAGE
    )
    kept_ids = {step.step_id for step in kept}
    return RoutedToolPlan(
        steps=tuple(
            step.model_copy(
                update={
                    "depends_on": tuple(
                        dependency for dependency in step.depends_on if dependency in kept_ids
                    )
                }
            )
            for step in kept
        ),
        missing_operations=plan.missing_operations,
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
    profile: SeriesProfile | None = None,
) -> str:
    """Build a natural grounded narrative that remains useful if the model fails."""

    language = response_language_for_fallback(question)
    metric = humanize_code(series.metric_code)
    subject = (
        "youth population"
        if series.metric_code == "population_count" and series.population_scope == "youth_specific"
        else metric.casefold()
    )
    if comparison is None:
        return _observation_overview_answer(
            series,
            profile or profile_series(series),
            filter_scope,
            language=language,
            metric=metric,
            citation_id=citation_id,
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
        if series.unit_code == "percent":
            # A rate moves in percentage points; a percent of a percent misleads.
            points_label = {"zh": " 個百分點", "vi": " điểm phần trăm"}.get(language, " pp")
            delta = f"{change.absolute_change:+.1f}{points_label}"
            figures = f"{change.first_value:.1f}% → {change.last_value:.1f}%"
        else:
            delta = (
                f"{change.percent_change:+.2f}%"
                if change.percent_change is not None
                else f"{change.absolute_change:+g} {series.unit_code}"
            )
            figures = f"{change.first_value:,.0f} → {change.last_value:,.0f}"
        bullets.append(f"- {name}: {figures} ({delta}) [{citation_id}]")
    # Age-band and sex series of one place are groups, not places.
    groups = any(":" in change.entity_id for change in changes)
    declined = sum(change.direction == "decreased" for change in changes)
    increased = sum(change.direction == "increased" for change in changes)
    if language == "vi":
        place = "nhóm" if groups else "địa điểm"
        summary = (
            f"{declined}/{len(changes)} {place} giảm và {increased}/{len(changes)} {place} tăng."
        )
        heading = f"Nhìn chung, xu hướng giữa các {place} không hoàn toàn giống nhau: {summary}"
    elif language == "zh":
        noun = "組" if groups else "地區"
        summary = f"{len(changes)}個{noun}中，{declined}個下降、{increased}個上升。"  # noqa: RUF001
        heading = f"整體來看，各{noun}的趨勢並不完全相同：{summary}"  # noqa: RUF001
    else:
        place = "groups" if groups else "locations"
        summary = f"{declined} of {len(changes)} {place} decreased; {increased} increased."
        heading = f"The trend varies across {place}: {summary}"
    scope_note = f" The figures cover {filter_scope}." if filter_scope else ""
    return f"{heading}{scope_note}\n\n" + "\n".join(bullets)


def _observation_overview_answer(
    series: ObservationSeries,
    profile: SeriesProfile,
    filter_scope: str | None,
    *,
    language: str,
    metric: str,
    citation_id: str,
) -> str:
    """Write a useful grounded overview even when no model composes the answer."""

    signals = profile.signals
    upward = [item for item in signals if (item.net_change_ratio or 0) > 0]
    downward = [item for item in signals if (item.net_change_ratio or 0) < 0]
    strongest_up = max(upward, key=lambda item: item.net_change_ratio or 0, default=None)
    strongest_down = min(downward, key=lambda item: item.net_change_ratio or 0, default=None)
    latest_period = profile.comparison_period or (profile.periods[-1] if profile.periods else None)
    latest = [item for item in signals if item.last_period == latest_period]
    highest = max(latest, key=lambda item: item.last_value, default=None)
    lowest = min(latest, key=lambda item: item.last_value, default=None)

    # ``readable_entity_name`` needs the requested display language, while the
    # fallback language helper intentionally uses compact string codes.
    def entity_name(signal: EntitySignal) -> str:
        locale = {
            "vi": NameLanguage.VIETNAMESE,
            "zh": NameLanguage.ZH_HANT,
        }.get(language, NameLanguage.ENGLISH)
        return readable_entity_name(signal.entity_id, signal.entity_name, locale)

    def movement_clause(signal: EntitySignal, direction: str) -> str:
        first = _format_observation_value(signal.first_value, series.unit_code)
        last = _format_observation_value(signal.last_value, series.unit_code)
        if language == "zh":
            verb = "上升" if direction == "up" else "下降"
            return (
                f"{entity_name(signal)}從{signal.first_period}的{first}{verb}至"
                f"{signal.last_period}的{last}"
            )
        if language == "vi":
            verb, connector = ("tăng", "lên") if direction == "up" else ("giảm", "xuống")
            return (
                f"{entity_name(signal)} {verb} từ {first} vào {signal.first_period} "
                f"{connector} {last} vào {signal.last_period}"
            )
        verb = "rose" if direction == "up" else "fell"
        return (
            f"{entity_name(signal)} {verb} from {first} in {signal.first_period} "
            f"to {last} in {signal.last_period}"
        )

    period_start = profile.periods[0] if profile.periods else "—"
    period_end = profile.periods[-1] if profile.periods else "—"
    scope_note = f" for {filter_scope}" if filter_scope else ""

    movement_parts: list[str] = []
    if strongest_up is not None:
        movement_parts.append(movement_clause(strongest_up, "up"))
    if strongest_down is not None:
        movement_parts.append(movement_clause(strongest_down, "down"))

    if language == "zh":
        opening = (
            f"{metric}\n\n這份概覽涵蓋{profile.entity_count}個地區，期間為"  # noqa: RUF001
            f"{period_start}至{period_end}，共{len(series.points)}筆已發布觀測值"  # noqa: RUF001
            f"。[{citation_id}]"
        )
        movement_summary = (
            "；".join(movement_parts) + f"。[{citation_id}]"  # noqa: RUF001
            if movement_parts
            else "目前資料未顯示可比較的跨期變化。"
        )
        distribution = (
            f"在{latest_period}，{entity_name(highest)}的報告值最高，為"  # noqa: RUF001
            f"{_format_observation_value(highest.last_value, series.unit_code)}；"  # noqa: RUF001
            f"{entity_name(lowest)}最低，為"  # noqa: RUF001
            f"{_format_observation_value(lowest.last_value, series.unit_code)}。"
            f"[{citation_id}] 這些差異描述資料呈現的分布，但不能單獨解釋成因。"  # noqa: RUF001
            if highest is not None and lowest is not None and highest is not lowest
            else "這些數值可描述目前分布，但不能單獨解釋成因。"  # noqa: RUF001
        )
        return f"{opening}\n\n{movement_summary}\n\n{distribution}"

    if language == "vi":
        opening = (
            f"{metric}\n\nTổng quan này bao phủ {profile.entity_count} địa điểm từ "
            f"{period_start} đến {period_end}, với {len(series.points)} quan sát đã công bố"
            f"{scope_note}. [{citation_id}]"
        )
        movement_summary = (
            "; ".join(movement_parts) + f". [{citation_id}]"
            if movement_parts
            else "Dữ liệu hiện chưa có đủ thay đổi theo thời gian để so sánh."
        )
        distribution = (
            f"Trong {latest_period}, {entity_name(highest)} có giá trị được báo cáo cao nhất "
            f"là {_format_observation_value(highest.last_value, series.unit_code)}, còn "
            f"{entity_name(lowest)} thấp nhất với "
            f"{_format_observation_value(lowest.last_value, series.unit_code)}. "
            f"[{citation_id}] Đây là khác biệt mô tả trong dữ liệu; riêng các con số này "
            "chưa giải thích được nguyên nhân."
            if highest is not None and lowest is not None and highest is not lowest
            else "Các số liệu mô tả phân bố hiện tại nhưng chưa giải thích được nguyên nhân."
        )
        return f"{opening}\n\n{movement_summary}\n\n{distribution}"

    opening = (
        f"{metric}\n\nThis overview covers {profile.entity_count} locations from "
        f"{period_start} to {period_end}, using {len(series.points)} published observations"
        f"{scope_note}. [{citation_id}]"
    )
    movement_summary = (
        "; ".join(movement_parts) + f". [{citation_id}]"
        if movement_parts
        else "The available data does not yet contain enough change over time to compare."
    )
    distribution = (
        f"In {latest_period}, {entity_name(highest)} has the highest reported value at "
        f"{_format_observation_value(highest.last_value, series.unit_code)}, while "
        f"{entity_name(lowest)} has the lowest at "
        f"{_format_observation_value(lowest.last_value, series.unit_code)}. "
        f"[{citation_id}] This is a descriptive difference in the published data; the figures "
        "alone do not explain its cause."
        if highest is not None and lowest is not None and highest is not lowest
        else "The figures describe the current distribution but do not explain its cause."
    )
    return f"{opening}\n\n{movement_summary}\n\n{distribution}"


def _format_observation_value(value: float, unit_code: str) -> str:
    if unit_code == "percent":
        return f"{value:,.1f}%"
    if value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


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


_FORECAST_ANSWER_DISTRICTS = 3


def _forecast_answer(result: ForecastResult) -> str:
    first = result.points[0]
    last = result.points[-1]
    finals = [point for point in result.points if point.year_gregorian == last.year_gregorian]
    if not any(point.components is not None for point in finals):
        return (
            f"Model {result.model_version} forecasts {humanize_code(result.metric_code)} from "
            f"{first.year_gregorian} to {last.year_gregorian}. The final point estimate is "
            f"{last.value:g}, with an uncertainty interval from {last.lower:g} to "
            f"{last.upper:g}."
        )
    sentences = [
        f"Model {result.model_version} forecasts {humanize_code(result.metric_code)} "
        f"to {last.year_gregorian}."
    ]
    for point in finals[:_FORECAST_ANSWER_DISTRICTS]:
        sentence = (
            f"{readable_entity_name(point.district_code)}: {point.value:,.0f} "
            f"(interval {point.lower:,.0f} to {point.upper:,.0f})"
        )
        parts = point.components
        if parts is not None:
            sentence += (
                f", from {parts.base_value:,.0f} in {parts.base_period}: {parts.entering:,.0f} "
                f"people reach 18, {parts.ageing_out:,.0f} pass 35, and the change beyond "
                f"ageing is {parts.net_change:,.0f}"
            )
        sentences.append(sentence + ".")
    if len(finals) > _FORECAST_ANSWER_DISTRICTS:
        sentences.append(
            f"{len(finals) - _FORECAST_ANSWER_DISTRICTS} more districts are in the forecast table."
        )
    accuracy = _final_horizon_accuracy(result)
    if accuracy is not None:
        selected, baseline = accuracy
        sentences.append(
            f"In backtests at a {selected.horizon_years}-year horizon this model missed by "
            f"{selected.mape_percent:.1f}% on average and by at most "
            f"{selected.p90_ape_percent:.1f}% in 90% of cases"
            + (
                f", against {baseline.mape_percent:.1f}% for the naive baseline."
                if baseline is not None
                else "."
            )
        )
    return " ".join(sentences)


def _forecast_accuracy_answer(result: ForecastResult) -> str | None:
    """Lead with the backtest when the question is how far the forecast can be trusted."""

    evaluation = result.evaluation
    if evaluation is None:
        return None
    selected = next(
        (item for item in evaluation.candidates if item.model == evaluation.selected_model), None
    )
    if selected is None:
        return None
    sentences = [
        f"Model {evaluation.selected_model} was selected because it beat "
        f"{evaluation.baseline_model} at every backtested horizon."
    ]
    for accuracy in selected.accuracy:
        baseline = evaluation.accuracy_of(evaluation.baseline_model, accuracy.horizon_years)
        sentences.append(
            f"At {accuracy.horizon_years} year{'s' if accuracy.horizon_years > 1 else ''} it "
            f"missed by {accuracy.mape_percent:.1f}% on average over {accuracy.samples} "
            f"district forecasts"
            + (f" (naive baseline {baseline.mape_percent:.1f}%)" if baseline is not None else "")
            + f", with a bias of {accuracy.bias_percent:.1f}%"
            + (
                f"; its interval contained {accuracy.interval_coverage:.0%} of outcomes."
                if accuracy.interval_coverage is not None
                else "."
            )
        )
    coverage = _coverage_sentence(evaluation)
    if coverage is not None:
        sentences.append(coverage)
    return " ".join(sentences)


def _coverage_sentence(evaluation: ForecastEvaluation) -> str | None:
    """How often intervals built from then-known errors contained what happened."""

    if evaluation.rolling_coverage is None or evaluation.rolling_samples is None:
        return None
    sentence = (
        f"Intervals target {evaluation.target_coverage:.0%} coverage; built only from errors "
        f"known at each origin, they contained {evaluation.rolling_coverage:.0%} of "
        f"{evaluation.rolling_samples} past outcomes"
    )
    if evaluation.small_area_coverage is not None:
        sentence += f" ({evaluation.small_area_coverage:.0%} in districts under 10,000 residents)"
    return sentence + "."


def _final_horizon_accuracy(
    result: ForecastResult,
) -> tuple[ForecastAccuracy, ForecastAccuracy | None] | None:
    """Backtest accuracy of the published and baseline models at the final horizon."""

    evaluation = result.evaluation
    if evaluation is None:
        return None
    horizon = max(point.year_gregorian for point in result.points) - int(evaluation.base_period[:4])
    selected = evaluation.accuracy_of(evaluation.selected_model, horizon)
    if selected is None:
        return None
    return selected, evaluation.accuracy_of(evaluation.baseline_model, horizon)


def _forecast_assumptions(result: ForecastResult) -> tuple[str, ...]:
    assumptions = [
        "Forecast points come from the latest published model available as of the request.",
        "Intervals describe model uncertainty and are not guaranteed outcomes.",
    ]
    evaluation = result.evaluation
    if evaluation is not None:
        assumptions.append(f"Method: {evaluation.method}; recent conditions continue.")
        assumptions.append(
            f"Interval half-widths are the {evaluation.error_quantile:.0%} quantile of past "
            "absolute backtest errors for the same horizon and district size."
        )
        coverage = _coverage_sentence(evaluation)
        if coverage is not None:
            assumptions.append(coverage)
    return tuple(assumptions)


def _forecast_warnings(result: ForecastResult) -> tuple[str, ...]:
    warnings = ["The forecast is predictive, not evidence of policy causation."]
    small = sorted(
        {point.district_code for point in result.points if point.small_area},
    )
    if small:
        names = ", ".join(readable_entity_name(code) for code in small)
        warnings.append(
            f"{names} {'has' if len(small) == 1 else 'have'} fewer than 10,000 residents; "
            "small-area forecasts miss by more, so their intervals are wider."
        )
    evaluation = result.evaluation
    if (
        evaluation is not None
        and evaluation.rolling_coverage is not None
        and evaluation.rolling_coverage < evaluation.target_coverage
    ):
        warnings.append(
            f"Intervals contained only {evaluation.rolling_coverage:.0%} of past outcomes, "
            f"below the {evaluation.target_coverage:.0%} target; the true range may be wider."
        )
    if any(point.components is not None for point in result.points):
        warnings.append(
            "Change beyond ageing combines migration, mortality, and registration changes; "
            "it is not migration alone."
        )
    return tuple(warnings)
