"""Shared response machinery for the copilot's answer pipelines.

Each pipeline — decision ranking, observations, multi-dataset joins, forecasts,
impact scenarios — retrieves different evidence, but every one of them ends the
same way: it records what it ran, attaches visualizations and limitations, and
returns one ``CopilotResponse``. That common tail lives here, so a pipeline
module carries only the part that is actually specific to its evidence.

``AnswerSupport`` is the injected collaborator holding the builders every
pipeline needs; the module-level functions are the small formatting rules that
must stay identical across pipelines (how a failure is traced, how a citation is
excerpted, which language a fallback narrative is written in).
"""

import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent.answering import AnswerComposer
from youth_compass.agent.contracts import (
    AnswerCompositionContext,
    CopilotResponse,
    CopilotStatus,
    DataLimitations,
    DatasetInspection,
    DecomposedQuery,
    EvidenceCitation,
    EvidenceExcerptRow,
    ObservationSeries,
    RoutedToolPlan,
    ToolTrace,
    VisualizationSpec,
)
from youth_compass.agent.limitations import DataLimitationsBuilder
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.agent.viz_selection import RejectedVisualization
from youth_compass.domain.contracts import DatasetMetadata
from youth_compass.domain.errors import SourceAcquisitionError
from youth_compass.ontology import (
    NameLanguage,
    extract_topics,
    humanize_code,
    question_language,
    readable_entity_name,
)
from youth_compass.ports import DataRequirement, SourceCandidate

#: How much of a failure message is kept in a tool trace. Long enough to name
#: the cause, short enough that a trace stays readable.
_TRACE_SUMMARY_LIMIT = 300

#: Evidence rows attached to one citation. The excerpt exists so a reader can
#: verify the number they were shown, not to ship the dataset.
_EXCERPT_ROW_LIMIT = 100


def unavailable_trace(tool: str, exc: Exception) -> ToolTrace:
    """Record that a tool could not run, with a bounded reason."""

    return ToolTrace(
        tool=tool,
        outcome="unavailable",
        summary=str(exc)[:_TRACE_SUMMARY_LIMIT],
    )


def answered(
    *,
    answer: str,
    now: datetime,
    decomposition: DecomposedQuery,
    routed_plan: RoutedToolPlan,
    trace: list[ToolTrace],
    **evidence: Any,
) -> CopilotResponse:
    """Wrap grounded evidence in the envelope every answered turn shares."""

    return CopilotResponse(
        status=CopilotStatus.ANSWERED,
        answer=answer,
        generated_at=now,
        decomposition=decomposition,
        routed_plan=routed_plan,
        tool_trace=tuple(trace),
        **evidence,
    )


def citation_from_series(
    citation_id: str,
    metadata: DatasetMetadata,
    series: ObservationSeries,
    question: str,
) -> EvidenceCitation:
    """Cite one dataset version and excerpt the rows behind its numbers."""

    language = name_language(question)
    return EvidenceCitation(
        citation_id=citation_id,
        dataset_id=metadata.dataset_id,
        dataset_version=metadata.version,
        quality_score=metadata.quality_score,
        retrieved_at=metadata.published_at or metadata.created_at,
        excerpt=tuple(
            EvidenceExcerptRow(
                entity_id=point.entity_id,
                entity_name=point.entity_name
                or readable_entity_name(point.entity_id, None, language),
                metric_code=series.metric_code,
                metric_name=humanize_code(series.metric_code),
                value=point.value,
                period=point.period,
            )
            for point in series.points[:_EXCERPT_ROW_LIMIT]
        ),
    )


def grounded_json(payload: object) -> str:
    """Serialize retrieved facts for the composer prompt, deterministically."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def name_language(question: str) -> NameLanguage:
    """Name places in the script the question was asked in."""

    return question_language(question)


def response_language_for_fallback(question: str) -> str:
    """The language a deterministic fallback narrative is written in."""

    language = question_language(question)
    if language is NameLanguage.ZH_HANT:
        return "zh"
    return "vi" if language is NameLanguage.VIETNAMESE else "en"


def inline_citations(citation_ids: tuple[str, ...]) -> str:
    """Render citation markers exactly as the composer's allowlist expects."""

    return " ".join(f"[{citation_id}]" for citation_id in citation_ids)


def discovery_warning(discovery_error: str | None) -> tuple[str, ...]:
    """State that source discovery itself failed, so the gap is not a verdict."""

    if discovery_error is None:
        return ()
    return (
        "Source discovery was unavailable, so no conclusion can be drawn about whether a "
        f"suitable external source exists: {discovery_error}",
    )


def data_gap_answer(
    question: str,
    source_candidates: tuple[SourceCandidate, ...],
    fallback: str,
    *,
    discovery_failed: bool = False,
) -> str:
    """Explain a data gap, and whether an allowlisted source could close it."""

    if not source_candidates:
        if discovery_failed:
            if question_language(question) is NameLanguage.ZH_HANT:
                return f"{fallback} 外部資料來源搜尋無法執行，因此目前無法判斷是否存在合適來源。"  # noqa: RUF001
            return (
                f"{fallback} The external source search could not run, so I cannot say "
                "whether a suitable source exists."
            )
        return fallback
    if question_language(question) is NameLanguage.ZH_HANT:
        return f"找到{len(source_candidates)}個可能補足資料缺口的官方來源。"
    return (
        f"I found {len(source_candidates)} official source candidate(s) that may fill the data gap."
    )


_ZH_METRICS = {
    "employment_count": "就業人數",
    "unemployment_count": "失業人數",
    "unemployment_rate": "失業率",
    "population_count": "人口數",
}


def _observation_gap_copy(question: str, warning: str) -> tuple[str, str]:
    """Localize the known observation-gap fallback without hiding its reason."""

    language = question_language(question)
    if language is not NameLanguage.ZH_HANT:
        return "There is not enough compatible observation data for this analysis.", warning
    prefix = "the published data does not measure "
    if warning.startswith(prefix) and "; available: " in warning:
        missing, available = warning.removeprefix(prefix).split("; available: ", 1)
        missing_names = "、".join(
            _ZH_METRICS.get(item.strip(), humanize_code(item.strip()))
            for item in missing.split(",")
        )
        available_names = "、".join(
            _ZH_METRICS.get(item.strip(), humanize_code(item.strip()))
            for item in available.split(",")
        )
        warning = f"已發布資料未包含{missing_names}；目前可用指標：{available_names}。"  # noqa: RUF001
    return "沒有足夠且相容的觀測資料可完成這項分析。", warning


class AnswerSupport:
    """The builders and shared endings every answer pipeline depends on."""

    def __init__(
        self,
        *,
        visualizations: VisualizationBuilder,
        limitations: DataLimitationsBuilder,
        composer: AnswerComposer,
        acquisition: DataAcquisitionService | None = None,
    ) -> None:
        self.visualizations = visualizations
        self.limitations = limitations
        self._composer = composer
        self._acquisition = acquisition

    async def compose(
        self,
        context: AnswerCompositionContext,
        trace: list[ToolTrace],
        *,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Narrate grounded facts, recording which composer produced the text.

        ``on_text`` is forwarded so a streaming transport can emit partial model
        output. It stays optional because most callers await the whole answer.
        """

        started = time.perf_counter()
        result = (
            await self._composer.compose(context)
            if on_text is None
            else await self._composer.compose(context, on_text)
        )
        trace.append(
            ToolTrace(
                tool="answer_composer",
                outcome=result.mode,
                summary=(f"composed grounded narrative with {len(result.citation_ids)} citations"),
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                # Only the model path reports usage; the deterministic template
                # leaves these unset rather than claiming zero, so a reader can
                # tell "free" from "not measured".
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        )
        return result.answer

    def trace_visualizations(
        self,
        trace: list[ToolTrace],
        visualizations: tuple[VisualizationSpec, ...],
        rejected: tuple[RejectedVisualization, ...] = (),
    ) -> None:
        """Record which grounded views were selected, and which were deliberately not.

        An answer that shows no chart is a decision, not an absence. Recording
        the rejected candidates and their reasons is what lets a reviewer tell
        the two apart without re-running the query.
        """

        if visualizations:
            trace.append(
                ToolTrace(
                    tool="visualization_builder",
                    outcome="ok",
                    summary=(
                        f"selected {len(visualizations)} grounded view(s): "
                        + ", ".join(item.type.value for item in visualizations)
                    ),
                )
            )
        if rejected:
            trace.append(
                ToolTrace(
                    tool="visualization_selector",
                    outcome="ok" if visualizations else "no_defensible_view",
                    summary="; ".join(
                        f"{item.visualization_id} cut ({item.reason.value}): {item.detail}"
                        for item in rejected
                    ),
                )
            )

    def trace_limitations(self, trace: list[ToolTrace], limitations: DataLimitations) -> None:
        """Record the coverage and freshness caveats attached to an answer."""

        coverage = limitations.coverage
        covered = (
            f"{coverage.observed_entity_count}/{coverage.expected_entity_count} entities"
            if coverage is not None
            else "coverage not applicable"
        )
        trace.append(
            ToolTrace(
                tool="audit_limitations",
                outcome="ok",
                summary=(
                    f"{covered}, basis {limitations.registration_basis.value}, "
                    f"{len(limitations.freshness)} dated source(s)"
                ),
            )
        )

    def discover_sources(
        self,
        decomposition: DecomposedQuery,
        trace: list[ToolTrace],
        *,
        metric_codes: tuple[str, ...] = (),
    ) -> tuple[DataRequirement, tuple[SourceCandidate, ...], str | None]:
        """Search allowlisted sources, reporting an outage as an outage.

        Returns the requirement, the candidates, and a failure reason. An empty
        candidate tuple alone cannot distinguish "discovery found nothing" from
        "discovery could not run", and telling a user no source exists when the
        search never happened is a wrong answer rather than a missing one.
        """

        named_topics = extract_topics(decomposition.original_question)
        requirement = DataRequirement(
            topic_terms=named_topics or decomposition.subject_terms,
            metric_codes=metric_codes or decomposition.metric_terms,
            entity_ids=decomposition.entity_ids,
            time_expression=decomposition.time_expression,
        )
        if self._acquisition is None:
            return requirement, (), None
        try:
            candidates = self._acquisition.discover(requirement)
        except SourceAcquisitionError as exc:
            trace.append(
                ToolTrace(
                    tool="discover_sources",
                    outcome="failed",
                    summary=str(exc)[:_TRACE_SUMMARY_LIMIT],
                )
            )
            return requirement, (), str(exc)
        trace.append(
            ToolTrace(
                tool="discover_sources",
                outcome="candidates" if candidates else "no_match",
                summary=f"found {len(candidates)} allowlisted source candidates",
            )
        )
        return requirement, candidates, None

    def observation_failure(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        warning: str,
        inspection: DatasetInspection | None = None,
        series: ObservationSeries | None = None,
    ) -> CopilotResponse:
        """Fail closed on missing observation data, offering a way to close the gap."""

        requirement, source_candidates, discovery_error = self.discover_sources(
            decomposition, trace
        )
        # Missing data is a question to the reader, asked in the conversation
        # from data_requirement and source_candidates. It is not a chart.
        visualizations: tuple[VisualizationSpec, ...] = ()
        fallback, localized_warning = _observation_gap_copy(
            decomposition.original_question, warning
        )
        return CopilotResponse(
            status=(
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            ),
            answer=data_gap_answer(
                decomposition.original_question,
                source_candidates,
                fallback,
                discovery_failed=discovery_error is not None,
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            dataset_inspection=inspection,
            observation_series=series,
            tool_trace=tuple(trace),
            warnings=(localized_warning, *discovery_warning(discovery_error)),
            data_requirement=requirement,
            source_candidates=source_candidates,
            visualizations=visualizations,
        )
