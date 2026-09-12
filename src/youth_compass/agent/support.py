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
import re
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
            return (
                f"{fallback} The external source search could not run, so I cannot say "
                "whether a suitable source exists."
            )
        return fallback
    if re.search(r"[\u3400-\u9fff]", question):
        return (
            f"目前已發布的資料不足，但找到{len(source_candidates)}個允許使用的外部資料來源。"  # noqa: RUF001
            "請選擇來源並完成資料映射與品質審核後，再繼續分析。"  # noqa: RUF001
        )
    return (
        f"The published catalog is insufficient, but {len(source_candidates)} allowlisted "
        "external source candidate(s) were found. Select a source and complete mapping and "
        "quality review before continuing the analysis."
    )


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

    async def compose(self, context: AnswerCompositionContext, trace: list[ToolTrace]) -> str:
        """Narrate grounded facts, recording which composer produced the text."""

        result = await self._composer.compose(context)
        trace.append(
            ToolTrace(
                tool="answer_composer",
                outcome=result.mode,
                summary=(f"composed grounded narrative with {len(result.citation_ids)} citations"),
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

        requirement = DataRequirement(
            topic_terms=decomposition.subject_terms,
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
        visualizations = self.visualizations.sources(
            decomposition.original_question, source_candidates
        )
        self.trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=(
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            ),
            answer=data_gap_answer(
                decomposition.original_question,
                source_candidates,
                "There is not enough compatible observation data for this analysis.",
                discovery_failed=discovery_error is not None,
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            dataset_inspection=inspection,
            observation_series=series,
            tool_trace=tuple(trace),
            warnings=(warning, *discovery_warning(discovery_error)),
            data_requirement=requirement,
            source_candidates=source_candidates,
            visualizations=visualizations,
        )
