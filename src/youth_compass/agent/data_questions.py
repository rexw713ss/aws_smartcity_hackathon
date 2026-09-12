"""Deterministic handlers for focused data questions.

A plain trend or comparison is answered by the observation executor. The
questions here ask something different about the same evidence: which districts
declined most, whether the latest year is complete, which values are estimates,
which population a dataset counts, what a new version changed, whether two
datasets join directly, and a per-district evidence summary.

Every figure is read from a published dataset version, a returned row, or catalog
metadata. The narrative written here is the grounded fallback; the configured
answer composer may rephrase it but cannot add a number or a citation.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from youth_compass.agent.contracts import (
    AnswerCompositionContext,
    CopilotResponse,
    CopilotStatus,
    DatasetInspection,
    DecomposedQuery,
    EntityChange,
    EntityComparison,
    EvidenceCitation,
    EvidenceExcerptRow,
    ObservationSeries,
    QuestionFocus,
    RoutedToolPlan,
    ToolTrace,
)
from youth_compass.agent.limitations import DataLimitationsBuilder
from youth_compass.agent.observation_tools import ObservationToolSuite
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus, PopulationScope
from youth_compass.domain.errors import QueryExecutionError, YouthCompassError
from youth_compass.mapping.geography import DISTRICTS
from youth_compass.ontology import (
    NameLanguage,
    extract_topics,
    humanize_code,
    question_language,
    readable_entity_name,
    resolve_district_name,
    resolve_topic_name,
)

type Composer = Callable[[AnswerCompositionContext, list[ToolTrace]], Awaitable[str]]

# The subject a question is about when it names none.
_DEFAULT_TOPIC = "population"
# How many districts a ranking names before pointing at the table.
_RANKING_LENGTH = 5
# The demo's review question asks which three districts to examine first.
_REVIEW_LIST_LENGTH = 3
_SUMMARY_DATASET_LIMIT = 4
_MONTHS_PER_YEAR = 12

_SCOPE_DESCRIPTIONS = {
    PopulationScope.YOUTH_SPECIFIC: "youth residents only",
    PopulationScope.DISTRICT_CONTEXT: "every resident of each district, not youth residents",
    PopulationScope.GENERAL_POPULATION: "the general population, not youth residents",
    PopulationScope.UNKNOWN: "a population the source did not specify",
}


def period_granularity(period: str) -> str:
    """Name the reporting granularity a canonical period string encodes."""

    return "month" if "-" in period else "year"


@dataclass(slots=True)
class _Turn:
    now: datetime
    decomposition: DecomposedQuery
    routed_plan: RoutedToolPlan
    trace: list[ToolTrace]
    min_quality_score: float

    @property
    def question(self) -> str:
        return self.decomposition.original_question

    @property
    def language(self) -> NameLanguage:
        return question_language(self.question)


@dataclass(frozen=True, slots=True)
class _Loaded:
    metadata: DatasetMetadata
    inspection: DatasetInspection
    series: ObservationSeries


class DataQuestionAnswerer:
    """Route a focused data question to its deterministic handler."""

    def __init__(
        self,
        tools: ObservationToolSuite,
        *,
        visualizations: VisualizationBuilder,
        limitations: DataLimitationsBuilder,
        compose: Composer,
    ) -> None:
        self._tools = tools
        self._visualizations = visualizations
        self._limitations = limitations
        self._compose = compose

    async def answer(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        min_quality_score: float,
    ) -> CopilotResponse | None:
        """Answer the focused question, or return None when no handler owns it."""

        handlers = {
            QuestionFocus.LARGEST_DECLINE: self._largest_decline,
            QuestionFocus.PRIORITY_EXPLANATION: self._priority_explanation,
            QuestionFocus.COMPLETENESS: self._completeness,
            QuestionFocus.ESTIMATES: self._estimates,
            QuestionFocus.POPULATION_SCOPE: self._population_scope,
            QuestionFocus.VERSION_CHANGES: self._version_changes,
            QuestionFocus.JOINABILITY: self._joinability,
            QuestionFocus.EVIDENCE_SUMMARY: self._evidence_summary,
        }
        handler = handlers.get(decomposition.focus) if decomposition.focus else None
        if handler is None:
            return None
        turn = _Turn(now, decomposition, routed_plan, trace, min_quality_score)
        try:
            return await handler(turn)
        except YouthCompassError as exc:
            trace.append(
                ToolTrace(tool=decomposition.focus.value, outcome="unavailable", summary=str(exc)[:300])
            )
            return self._response(
                turn,
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=(
                    "The published data cannot answer this question as asked: "
                    f"{exc}. No partial answer was produced."
                ),
                warnings=(str(exc),),
            )

    # --- ranking -----------------------------------------------------------

    async def _largest_decline(self, turn: _Turn) -> CopilotResponse:
        loaded, comparison = self._ranked_changes(turn)
        declines = [change for change in _by_decline(comparison.changes) if _declined(change)]
        citation = self._citation("data-1", loaded, turn.language)
        first, last = _span(comparison.changes)
        if not declines:
            fallback = (
                f"No district lost youth population between {first} and {last}: all "
                f"{len(comparison.changes)} districts held steady or grew. [{citation.citation_id}]"
            )
        else:
            lines = [
                f"{rank}. {self._name(change, turn)}: {change.percent_change:+.2f}% "
                f"({change.first_value:,.0f} to {change.last_value:,.0f})"
                for rank, change in enumerate(declines[:_RANKING_LENGTH], start=1)
            ]
            fallback = (
                f"Between {first} and {last}, {len(declines)} of {len(comparison.changes)} "
                "districts lost youth population. The largest shares lost were:\n\n"
                + "\n".join(lines)
                + f"\n\nShares compare each district's first and last published observation. "
                f"[{citation.citation_id}]"
            )
        return await self._observation_response(turn, loaded, comparison, citation, fallback)

    async def _priority_explanation(self, turn: _Turn) -> CopilotResponse:
        if not turn.decomposition.entity_ids:
            return self._clarify(turn, "Which district should the priority explanation cover?")
        loaded, comparison = self._ranked_changes(turn)
        ranked = _by_decline(comparison.changes)
        wanted = {_district_key(entity) for entity in turn.decomposition.entity_ids}
        citation = self._citation("data-1", loaded, turn.language)
        paragraphs: list[str] = []
        for position, change in enumerate(ranked, start=1):
            if _district_key(change.entity_id) not in wanted:
                continue
            name = self._name(change, turn)
            movement = (
                f"lost {abs(change.percent_change or 0):.2f}% of its youth population"
                if _declined(change)
                else f"gained {abs(change.percent_change or 0):.2f}% in youth population"
            )
            standing = (
                f"That places it {position} of {len(ranked)} districts, within the "
                f"{_REVIEW_LIST_LENGTH} steepest declines a review would examine first."
                if _declined(change) and position <= _REVIEW_LIST_LENGTH
                else f"That places it {position} of {len(ranked)} districts, outside the "
                f"{_REVIEW_LIST_LENGTH} steepest declines."
            )
            paragraphs.append(
                f"{name} {movement} between {change.first_period} and {change.last_period} "
                f"({change.first_value:,.0f} to {change.last_value:,.0f}). {standing}"
            )
        if not paragraphs:
            raise QueryExecutionError(
                "the requested district has no published youth population series"
            )
        fallback = (
            "Priority here is the ranking by share of youth population lost; no other score "
            "is applied.\n\n" + "\n\n".join(paragraphs) + f" [{citation.citation_id}]"
        )
        return await self._observation_response(turn, loaded, comparison, citation, fallback)

    def _ranked_changes(self, turn: _Turn) -> tuple[_Loaded, EntityComparison]:
        # A ranking is across every district unless the question named some; the
        # explanation always ranks citywide so a position means the same thing.
        citywide = turn.decomposition.focus is QuestionFocus.PRIORITY_EXPLANATION
        scope = turn.decomposition.model_copy(update={"entity_ids": ()}) if citywide else None
        loaded = self._load(turn, scope or turn.decomposition, default_topic=True)
        comparison = self._tools.compare_entities.execute(loaded.series)
        turn.trace.append(
            ToolTrace(
                tool="compare_entities",
                outcome="ok",
                summary=f"ranked {len(comparison.changes)} districts by share of change",
            )
        )
        return loaded, comparison

    # --- data quality ------------------------------------------------------

    async def _completeness(self, turn: _Turn) -> CopilotResponse:
        loaded = self._load(turn, turn.decomposition.model_copy(update={"entity_ids": ()}), default_topic=True)
        citation = self._citation("data-1", loaded, turn.language)
        periods = sorted({point.period for point in loaded.series.points})
        latest = periods[-1]
        name = humanize_code(loaded.metadata.dataset_id)
        entities_latest = {
            _district_key(point.entity_id)
            for point in loaded.series.points
            if point.period == latest
        }
        coverage = f"{len(entities_latest)} of {len(DISTRICTS)} districts"
        if period_granularity(latest) == "month":
            months_by_year: dict[str, set[str]] = {}
            for period in periods:
                year, month = period.split("-", 1)
                months_by_year.setdefault(year, set()).add(month)
            latest_year = latest.split("-", 1)[0]
            present = len(months_by_year[latest_year])
            complete_years = sorted(
                year for year, months in months_by_year.items() if len(months) == _MONTHS_PER_YEAR
            )
            if present == _MONTHS_PER_YEAR:
                verdict = (
                    f"Yes. {name} reports monthly and {latest_year} has all "
                    f"{_MONTHS_PER_YEAR} months."
                )
            else:
                last_complete = (
                    f" The latest complete year is {complete_years[-1]}."
                    if complete_years
                    else " No year in the dataset has all twelve months."
                )
                verdict = (
                    f"No. {name} reports monthly and its latest year, {latest_year}, has "
                    f"{present} of {_MONTHS_PER_YEAR} months (through {latest}).{last_complete}"
                )
        else:
            verdict = (
                f"{'Yes' if len(entities_latest) == len(DISTRICTS) else 'No'}. {name} reports "
                f"yearly and its latest year, {latest}, covers {coverage}."
            )
        fallback = f"{verdict} The latest period, {latest}, covers {coverage}. [{citation.citation_id}]"
        turn.trace.append(
            ToolTrace(tool="audit_completeness", outcome="ok", summary=verdict[:300])
        )
        return await self._single_dataset_response(turn, loaded, citation, fallback)

    async def _estimates(self, turn: _Turn) -> CopilotResponse:
        published = self._published()[:_SUMMARY_DATASET_LIMIT]
        if not published:
            raise QueryExecutionError("no published dataset is available to audit")
        citations: list[EvidenceCitation] = []
        lines: list[str] = []
        for index, metadata in enumerate(published, start=1):
            loaded = self._load(
                turn,
                turn.decomposition.model_copy(update={"entity_ids": ()}),
                dataset_id=metadata.dataset_id,
            )
            citation = self._citation(f"data-{index}", loaded, turn.language)
            citations.append(citation)
            points = loaded.series.points
            estimated = [point for point in points if point.estimated_value > 0]
            name = humanize_code(metadata.dataset_id)
            if not estimated:
                lines.append(
                    f"- {name}: none of {len(points):,} observations include an estimated "
                    f"value; every value is a reported count. [{citation.citation_id}]"
                )
                continue
            examples = ", ".join(
                f"{readable_entity_name(point.entity_id, point.entity_name, turn.language)} "
                f"{point.period} ({point.estimated_value:,.0f} of {point.value:,.0f})"
                for point in estimated[:5]
            )
            lines.append(
                f"- {name}: {len(estimated):,} of {len(points):,} observations include an "
                f"estimated portion, for example {examples}. [{citation.citation_id}]"
            )
        turn.trace.append(
            ToolTrace(
                tool="audit_estimates",
                outcome="ok",
                summary=f"audited estimated values across {len(published)} published datasets",
            )
        )
        fallback = (
            "Estimated values come from age bands that only partly overlap the youth range, "
            "which the ingestion weights instead of reporting directly.\n\n" + "\n".join(lines)
        )
        return await self._citations_response(turn, tuple(citations), fallback)

    # --- catalog semantics -------------------------------------------------

    async def _population_scope(self, turn: _Turn) -> CopilotResponse:
        topics = [topic for topic in extract_topics(turn.question) if topic != _DEFAULT_TOPIC]
        if not topics:
            return self._clarify(turn, "Which dataset's population should be checked?")
        topic = topics[0]
        records = [item for item in self._catalog_records() if resolve_topic_name(item.topic) == topic]
        subject = humanize_code(topic).casefold()
        rule = (
            "Sources without a youth age breakdown are ingested as district context and are "
            "never labelled youth-specific."
        )
        if not records:
            answer = (
                f"No {subject} dataset is in the catalog, so this cannot be checked against "
                f"published data. {rule}"
            )
            turn.trace.append(ToolTrace(tool="search_catalog", outcome="no_match", summary=answer[:300]))
            return self._response(
                turn, status=CopilotStatus.INSUFFICIENT_DATA, answer=answer, warnings=(answer,)
            )
        metadata = records[0]
        if metadata.status is not DatasetStatus.PUBLISHED:
            answer = (
                f"The {subject} dataset is not published (its latest ingestion is "
                f"{metadata.status.value.replace('_', ' ')}), so no answer uses it. {rule}"
            )
            turn.trace.append(ToolTrace(tool="search_catalog", outcome="unavailable", summary=answer[:300]))
            return self._response(
                turn, status=CopilotStatus.INSUFFICIENT_DATA, answer=answer, warnings=(answer,)
            )
        inspection = self._tools.inspect_dataset.execute_for_dataset(
            turn.decomposition, metadata.dataset_id, min_quality_score=turn.min_quality_score
        )
        citation = _catalog_citation("data-1", metadata)
        scope = metadata.population_scope
        youth = scope is PopulationScope.YOUTH_SPECIFIC
        fallback = (
            f"{'Yes' if youth else 'No'}. The published {subject} dataset counts "
            f"{_SCOPE_DESCRIPTIONS[scope]}"
            + (
                "."
                if youth
                else f", so its {humanize_code(inspection.metric_code).casefold()} describes the "
                "whole district and cannot be read as a figure for youth residents."
            )
            + f" [{citation.citation_id}]"
        )
        turn.trace.append(
            ToolTrace(
                tool="inspect_dataset",
                outcome="ok",
                summary=f"{metadata.dataset_id} population scope is {scope.value}",
            )
        )
        return await self._citations_response(turn, (citation,), fallback, inspection=inspection)

    async def _version_changes(self, turn: _Turn) -> CopilotResponse:
        topic = next(iter(extract_topics(turn.question)), None)
        if topic is None:
            return self._clarify(turn, "Which dataset's newest version should be described?")
        records = [item for item in self._catalog_records() if resolve_topic_name(item.topic) == topic]
        subject = humanize_code(topic).casefold()
        if not records:
            answer = f"No {subject} dataset is in the catalog, so there is no version to compare."
            turn.trace.append(ToolTrace(tool="search_catalog", outcome="no_match", summary=answer))
            return self._response(
                turn, status=CopilotStatus.INSUFFICIENT_DATA, answer=answer, warnings=(answer,)
            )
        dataset_id = records[0].dataset_id
        versions = [
            item for item in self._tools.catalog.list_versions(dataset_id) if not item.version.startswith("received-")
        ]
        if not versions:
            raise QueryExecutionError(f"{dataset_id} has no processed version")
        newest = versions[-1]
        published = [item for item in versions if item.status is DatasetStatus.PUBLISHED]
        turn.trace.append(
            ToolTrace(
                tool="search_catalog",
                outcome="ok",
                summary=f"read {len(versions)} processed versions of {dataset_id}",
            )
        )
        if newest.status is not DatasetStatus.PUBLISHED:
            live = published[-1] if published else None
            consequence = (
                "Answers still use the previously published version."
                if live
                else "No version of it has ever been published, so no answer uses it."
            )
            answer = (
                f"Nothing changed in the published {subject} data. The newest {subject} file was "
                f"not published: its ingestion ended {newest.status.value.replace('_', ' ')} "
                f"with a quality score of {newest.quality_score:.2f}. {consequence}"
            )
            return self._response(
                turn,
                status=CopilotStatus.ANSWERED,
                answer=answer,
                warnings=(f"{dataset_id} newest version is {newest.status.value}",),
            )
        if len(published) < 2:
            citation = _catalog_citation("data-1", newest)
            fallback = (
                f"The {subject} dataset has one published version, so there is no earlier "
                f"version to compare it with. [{citation.citation_id}]"
            )
            return await self._citations_response(turn, (citation,), fallback)
        previous, current = published[-2], published[-1]
        before = self._tools.inspect_dataset.execute_for_version(turn.decomposition, previous)
        after = self._tools.inspect_dataset.execute_for_version(turn.decomposition, current)
        changes = _inspection_changes(before, after, previous, current)
        citations = (_catalog_citation("data-1", current), _catalog_citation("data-2", previous))
        fallback = (
            f"Comparing the current {subject} version with the one it replaced:\n\n"
            + "\n".join(f"- {line}" for line in changes)
            + " [data-1] [data-2]"
        )
        turn.trace.append(
            ToolTrace(tool="compare_versions", outcome="ok", summary="; ".join(changes)[:300])
        )
        return await self._citations_response(turn, citations, fallback, inspection=after)

    async def _joinability(self, turn: _Turn) -> CopilotResponse:
        published = self._published()
        named = [
            item
            for topic in extract_topics(turn.question)
            for item in published
            if resolve_topic_name(item.topic) == topic
        ]
        # "this new dataset" names no subject: it is the most recently published
        # table other than the ones the question did name.
        others = sorted(
            (item for item in published if item not in named),
            key=lambda item: item.published_at or item.created_at,
        )
        pair = list(dict.fromkeys([*named, *reversed(others)]))[:2]
        if len(pair) < 2:
            raise QueryExecutionError("fewer than two published datasets are available to compare")
        inspections = [
            self._tools.inspect_dataset.execute_for_dataset(
                turn.decomposition, item.dataset_id, min_quality_score=turn.min_quality_score
            )
            for item in pair
        ]
        grains = [period_granularity(inspection.period_end) for inspection in inspections]
        names = [humanize_code(item.dataset_id) for item in pair]
        keyed = all("district_code" in item.grain.dimensions for item in pair)
        scopes = {item.population_scope for item in pair}
        citations = tuple(_catalog_citation(f"data-{index}", item) for index, item in enumerate(pair, start=1))
        if grains[0] == grains[1] and keyed:
            verdict = (
                f"Yes. {names[0]} and {names[1]} both report by {grains[0]} and are keyed by "
                "canonical district code, so an exact join on district and period applies."
            )
        elif keyed:
            monthly = names[grains.index("month")]
            yearly = names[grains.index("year")]
            verdict = (
                f"Not directly. {yearly} reports by year while {monthly} reports by month, so no "
                "period key matches exactly. Both are keyed by canonical district code, so they "
                f"can be combined on district and year once {monthly} is aligned to each year's "
                "closing month, which is valid for a point-in-time count but not for a "
                "within-year total."
            )
        else:
            verdict = (
                f"No. {names[0]} and {names[1]} do not share a canonical district key, so they "
                "cannot be aligned without a spatial mapping this system does not perform."
            )
        if len(scopes) > 1:
            verdict += (
                " They also count different populations ("
                + ", ".join(sorted(scope.value for scope in scopes))
                + "), so a combined table compares two groups rather than one."
            )
        turn.trace.append(ToolTrace(tool="validate_analysis_plan", outcome="ok", summary=verdict[:300]))
        fallback = verdict + " [data-1] [data-2]"
        return await self._citations_response(turn, citations, fallback, inspection=inspections[0])

    # --- summary -----------------------------------------------------------

    async def _evidence_summary(self, turn: _Turn) -> CopilotResponse:
        entities = turn.decomposition.entity_ids
        if not entities:
            return self._clarify(turn, "Which districts should the evidence summary cover?")
        published = self._published()[:_SUMMARY_DATASET_LIMIT]
        if not published:
            raise QueryExecutionError("no published dataset is available to summarize")
        scoped = turn.decomposition.model_copy(update={"time_expression": None})
        citations: list[EvidenceCitation] = []
        sections: list[str] = []
        for metadata in published:
            try:
                loaded = self._load(turn, scoped, dataset_id=metadata.dataset_id)
            except YouthCompassError as exc:
                sections.append(f"{humanize_code(metadata.dataset_id)}: not available for these districts ({exc}).")
                continue
            citation = self._citation(f"data-{len(citations) + 1}", loaded, turn.language)
            citations.append(citation)
            header = (
                f"{humanize_code(metadata.dataset_id)} ({_SCOPE_DESCRIPTIONS[metadata.population_scope]}, "
                f"{period_granularity(loaded.inspection.period_end)}ly, "
                f"{loaded.inspection.period_start} to {loaded.inspection.period_end}) "
                f"[{citation.citation_id}]"
            )
            try:
                comparison = self._tools.compare_entities.execute(loaded.series)
                rows = [
                    f"- {self._name(change, turn)}: {change.last_value:,.0f} in {change.last_period}, "
                    f"{change.percent_change:+.2f}% since {change.first_period}"
                    if change.percent_change is not None
                    else f"- {self._name(change, turn)}: {change.last_value:,.0f} in {change.last_period}"
                    for change in comparison.changes
                ]
            except YouthCompassError:
                latest = _latest_points(loaded.series)
                rows = [
                    f"- {readable_entity_name(point.entity_id, point.entity_name, turn.language)}: "
                    f"{point.value:,.0f} in {point.period}"
                    for point in latest
                ]
            sections.append(header + "\n" + "\n".join(rows))
        if not citations:
            raise QueryExecutionError("no published dataset covers the selected districts")
        names = ", ".join(
            readable_entity_name(entity, None, turn.language) for entity in entities
        )
        turn.trace.append(
            ToolTrace(
                tool="compose_evidence_summary",
                outcome="ok",
                summary=f"summarized {len(citations)} published datasets for {len(entities)} districts",
            )
        )
        fallback = f"Evidence summary for {names}\n\n" + "\n\n".join(sections)
        return await self._citations_response(turn, tuple(citations), fallback)

    # --- shared plumbing ---------------------------------------------------

    def _load(
        self,
        turn: _Turn,
        decomposition: DecomposedQuery,
        *,
        dataset_id: str | None = None,
        default_topic: bool = False,
    ) -> _Loaded:
        del default_topic  # Selection already defaults to population; kept for readability.
        inspect = self._tools.inspect_dataset
        inspection = (
            inspect.execute_for_dataset(
                decomposition, dataset_id, min_quality_score=turn.min_quality_score
            )
            if dataset_id
            else inspect.execute(decomposition, min_quality_score=turn.min_quality_score)
        )
        metadata = self._tools.catalog.get(inspection.dataset_id)
        if metadata.version != inspection.dataset_version:
            raise QueryExecutionError("the published dataset version changed during analysis")
        series = self._tools.query_observations.execute(decomposition, inspection, metadata)
        turn.trace.extend(
            (
                ToolTrace(
                    tool="inspect_dataset",
                    outcome="ok",
                    summary=f"resolved {metadata.dataset_id} {inspection.metric_code} "
                    f"{inspection.period_start} to {inspection.period_end}",
                ),
                ToolTrace(
                    tool="query_observations",
                    outcome="ok",
                    summary=f"retrieved {len(series.points)} observations from {metadata.dataset_id}",
                ),
            )
        )
        return _Loaded(metadata, inspection, series)

    def _published(self) -> list[DatasetMetadata]:
        return sorted(
            (item for item in self._tools.catalog.list_datasets() if item.status is DatasetStatus.PUBLISHED),
            key=lambda item: (resolve_topic_name(item.topic) != _DEFAULT_TOPIC, item.dataset_id),
        )

    def _catalog_records(self) -> list[DatasetMetadata]:
        return list(self._tools.catalog.list_datasets())

    def _name(self, change: EntityChange, turn: _Turn) -> str:
        return readable_entity_name(change.entity_id, change.entity_name, turn.language)

    def _citation(self, citation_id: str, loaded: _Loaded, language: NameLanguage) -> EvidenceCitation:
        return EvidenceCitation(
            citation_id=citation_id,
            dataset_id=loaded.metadata.dataset_id,
            dataset_version=loaded.metadata.version,
            quality_score=loaded.metadata.quality_score,
            retrieved_at=loaded.metadata.published_at or loaded.metadata.created_at,
            excerpt=tuple(
                EvidenceExcerptRow(
                    entity_id=point.entity_id,
                    entity_name=readable_entity_name(point.entity_id, point.entity_name, language),
                    metric_code=loaded.series.metric_code,
                    metric_name=humanize_code(loaded.series.metric_code),
                    value=point.value,
                    period=point.period,
                )
                for point in _latest_points(loaded.series)[:100]
            ),
        )

    async def _narrate(
        self, turn: _Turn, fallback: str, citations: tuple[EvidenceCitation, ...], facts: object
    ) -> str:
        return await self._compose(
            AnswerCompositionContext(
                question=turn.question,
                analysis_type="data_question",
                grounded_facts_json=_grounded_json(
                    {
                        "focus": turn.decomposition.focus.value if turn.decomposition.focus else None,
                        "facts": facts,
                        "citations": [item.model_dump(mode="json") for item in citations],
                    }
                ),
                allowed_citation_ids=tuple(item.citation_id for item in citations),
                fallback_answer=fallback,
            ),
            turn.trace,
        )

    async def _observation_response(
        self,
        turn: _Turn,
        loaded: _Loaded,
        comparison: EntityComparison,
        citation: EvidenceCitation,
        fallback: str,
    ) -> CopilotResponse:
        answer = await self._narrate(
            turn, fallback, (citation,), {"comparison": comparison.model_dump(mode="json")}
        )
        visualizations = self._visualizations.observations(
            turn.question, loaded.series, comparison, (citation.citation_id,)
        )
        limitations = self._limitations.build(
            now=turn.now,
            citations=(citation,),
            observed_entity_ids=[change.entity_id for change in comparison.changes],
            requested_entity_ids=turn.decomposition.entity_ids,
            catalog_terms=(loaded.metadata.topic, loaded.metadata.dataset_id, loaded.series.metric_code),
            series=loaded.series,
        )
        return self._response(
            turn,
            status=CopilotStatus.ANSWERED,
            answer=answer,
            citations=(citation,),
            inspection=loaded.inspection,
            series=loaded.series,
            comparison=comparison,
            visualizations=visualizations,
            limitations=limitations,
        )

    async def _single_dataset_response(
        self, turn: _Turn, loaded: _Loaded, citation: EvidenceCitation, fallback: str
    ) -> CopilotResponse:
        answer = await self._narrate(
            turn, fallback, (citation,), {"inspection": loaded.inspection.model_dump(mode="json")}
        )
        limitations = self._limitations.build(
            now=turn.now,
            citations=(citation,),
            observed_entity_ids=[point.entity_id for point in loaded.series.points],
            catalog_terms=(loaded.metadata.topic, loaded.metadata.dataset_id, loaded.series.metric_code),
            series=loaded.series,
        )
        return self._response(
            turn,
            status=CopilotStatus.ANSWERED,
            answer=answer,
            citations=(citation,),
            inspection=loaded.inspection,
            visualizations=self._visualizations.inspection(turn.question, loaded.inspection),
            limitations=limitations,
        )

    async def _citations_response(
        self,
        turn: _Turn,
        citations: tuple[EvidenceCitation, ...],
        fallback: str,
        *,
        inspection: DatasetInspection | None = None,
    ) -> CopilotResponse:
        answer = await self._narrate(turn, fallback, citations, {"summary": fallback})
        limitations = self._limitations.build(
            now=turn.now,
            citations=citations,
            observed_entity_ids=[row.entity_id for item in citations for row in item.excerpt],
            requested_entity_ids=turn.decomposition.entity_ids,
        )
        return self._response(
            turn,
            status=CopilotStatus.ANSWERED,
            answer=answer,
            citations=citations,
            inspection=inspection,
            limitations=limitations,
        )

    def _clarify(self, turn: _Turn, question: str) -> CopilotResponse:
        turn.trace.append(ToolTrace(tool="query_decomposer", outcome="clarification", summary=question))
        return self._response(
            turn,
            status=CopilotStatus.UNSUPPORTED_QUESTION,
            answer=question,
            warnings=("No data tool was executed before clarification.",),
        )

    def _response(
        self,
        turn: _Turn,
        *,
        status: CopilotStatus,
        answer: str,
        warnings: tuple[str, ...] = (),
        citations: tuple[EvidenceCitation, ...] = (),
        inspection: DatasetInspection | None = None,
        series: ObservationSeries | None = None,
        comparison: EntityComparison | None = None,
        visualizations: tuple = (),  # type: ignore[type-arg]
        limitations: object = None,
    ) -> CopilotResponse:
        return CopilotResponse(
            status=status,
            answer=answer,
            generated_at=turn.now,
            decomposition=turn.decomposition,
            routed_plan=turn.routed_plan,
            dataset_inspection=inspection,
            observation_series=series,
            comparison=comparison,
            citations=citations,
            tool_trace=tuple(turn.trace),
            warnings=warnings,
            visualizations=visualizations,
            limitations=limitations,  # type: ignore[arg-type]
        )


def _by_decline(changes: tuple[EntityChange, ...]) -> list[EntityChange]:
    """Order changes from the steepest proportional loss to the largest gain."""

    return sorted(
        (change for change in changes if change.percent_change is not None),
        key=lambda change: (change.percent_change, change.entity_id),
    )


def _declined(change: EntityChange) -> bool:
    return change.percent_change is not None and change.percent_change < 0


def _span(changes: tuple[EntityChange, ...]) -> tuple[str, str]:
    return (
        min(change.first_period for change in changes),
        max(change.last_period for change in changes),
    )


def _district_key(entity_id: str) -> str:
    district = resolve_district_name(entity_id).district
    return district.code if district is not None else entity_id.casefold()


def _latest_points(series: ObservationSeries) -> list:  # type: ignore[type-arg]
    latest: dict[str, object] = {}
    for point in series.points:
        current = latest.get(point.entity_id)
        if current is None or point.period > current.period:  # type: ignore[attr-defined]
            latest[point.entity_id] = point
    return sorted(latest.values(), key=lambda point: point.entity_id)  # type: ignore[attr-defined]


def _catalog_citation(citation_id: str, metadata: DatasetMetadata) -> EvidenceCitation:
    return EvidenceCitation(
        citation_id=citation_id,
        dataset_id=metadata.dataset_id,
        dataset_version=metadata.version,
        quality_score=metadata.quality_score,
        retrieved_at=metadata.published_at or metadata.created_at,
    )


def _inspection_changes(
    before: DatasetInspection,
    after: DatasetInspection,
    previous: DatasetMetadata,
    current: DatasetMetadata,
) -> list[str]:
    """List what differs between two published versions, from their inspections."""

    lines: list[str] = []
    if (before.period_start, before.period_end) != (after.period_start, after.period_end):
        lines.append(
            f"coverage moved from {before.period_start}–{before.period_end} to "
            f"{after.period_start}–{after.period_end}"
        )
    if before.entity_count != after.entity_count:
        lines.append(f"districts covered changed from {before.entity_count} to {after.entity_count}")
    added = sorted(set(after.available_metrics) - set(before.available_metrics))
    removed = sorted(set(before.available_metrics) - set(after.available_metrics))
    if added:
        lines.append("metrics added: " + ", ".join(humanize_code(code) for code in added))
    if removed:
        lines.append("metrics removed: " + ", ".join(humanize_code(code) for code in removed))
    if previous.quality_score != current.quality_score:
        lines.append(
            f"quality score changed from {previous.quality_score:.2f} to {current.quality_score:.2f}"
        )
    published_before = previous.published_at or previous.created_at
    published_after = current.published_at or current.created_at
    lines.append(
        f"published {published_after:%Y-%m-%d}, replacing the version published "
        f"{published_before:%Y-%m-%d}"
    )
    if len(lines) == 1:
        lines.insert(0, "coverage, districts, metrics, and quality are unchanged")
    return lines


def _grounded_json(payload: object) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
