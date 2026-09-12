"""Deterministic, evidence-grounded copilot orchestration."""

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent.answering import (
    AnswerComposer,
    DeterministicAnswerComposer,
    FallbackAnswerComposer,
)
from youth_compass.agent.contracts import (
    AnalysisOperation,
    AnswerCompositionContext,
    CandidateInsight,
    CopilotIntent,
    CopilotResponse,
    CopilotStatus,
    DatasetInspection,
    DecisionExecutionPlan,
    DecomposedQuery,
    EntityComparison,
    EvidenceCitation,
    FeatureContributionInsight,
    ObservationSeries,
    RoutedToolPlan,
    ToolCapability,
    ToolTrace,
    VisualizationSpec,
)
from youth_compass.agent.observation_tools import ObservationToolSuite
from youth_compass.agent.planning import (
    DeterministicQueryDecomposer,
    QueryDecomposer,
    SmartToolRouter,
    ToolCapabilityRegistry,
    default_decision_capabilities,
    register_acquisition_capabilities,
    register_observation_capabilities,
)
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.decisioning import (
    CandidateScore,
    DecisionProfileRegistry,
    DecisionScoringEngine,
    FeatureProvider,
    FeatureQuery,
    FeatureRegistry,
    FeatureValue,
)
from youth_compass.domain.errors import (
    ModelInvocationError,
    QueryExecutionError,
    SourceAcquisitionError,
    YouthCompassError,
)
from youth_compass.ports import DataRequirement, ModelProvider, ModelRequest, SourceCandidate


class CopilotPlanner(Protocol):
    """Convert natural language into an allowlisted, schema-validated intent."""

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        """Return a supported intent, or None when no profile can answer."""
        ...


class DeterministicCopilotPlanner:
    """Offline planner for the two reference location decisions."""

    _HOME_TERMS = (
        "mua nhà",
        "nha o dau",
        "nhà ở đâu",
        "home buying",
        "buy a home",
        "buy house",
        "housing location",
        "買房",
        "購屋",
    )
    _CHARGER_TERMS = (
        "trụ sạc",
        "trạm sạc",
        "tru sac",
        "tram sac",
        "ev charger",
        "charging station",
        "charger placement",
        "充電站",
        "充電樁",
    )

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        normalized = " ".join(question.casefold().split())
        if any(term in normalized for term in self._HOME_TERMS):
            return CopilotIntent(profile_code="home_buying", entity_ids=entity_ids)
        if any(term in normalized for term in self._CHARGER_TERMS):
            return CopilotIntent(profile_code="ev_charger_placement", entity_ids=entity_ids)
        return None


class ModelCopilotPlanner:
    """Schema-constrained planner for a Bedrock-backed ModelProvider."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        allowed_profiles: tuple[str, ...] = ("home_buying", "ev_charger_placement"),
    ) -> None:
        self._provider = provider
        self._allowed_profiles = frozenset(allowed_profiles)

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        response = await self._provider.generate(
            ModelRequest(
                system=(
                    "Classify the user's decision question. Return only JSON matching the "
                    "provided schema. Never invent a profile. Use one of: "
                    + ", ".join(sorted(self._allowed_profiles))
                ),
                prompt=json.dumps(
                    {"question": question, "entity_ids": entity_ids},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                temperature=0,
                max_tokens=200,
                response_schema=CopilotIntent.model_json_schema(),
            )
        )
        try:
            intent = CopilotIntent.model_validate_json(response.text)
        except ValidationError as exc:
            raise ModelInvocationError("model returned an invalid copilot intent") from exc
        if intent.profile_code not in self._allowed_profiles:
            return None
        return intent.model_copy(update={"entity_ids": entity_ids})


class GroundedCopilotService:
    """Plan, retrieve, rank, and explain without delegating facts to an LLM."""

    def __init__(
        self,
        *,
        feature_provider: FeatureProvider,
        feature_registry: FeatureRegistry,
        profile_registry: DecisionProfileRegistry,
        planner: CopilotPlanner | None = None,
        decomposer: QueryDecomposer | None = None,
        capabilities: ToolCapabilityRegistry | None = None,
        observation_tools: ObservationToolSuite | None = None,
        answer_composer: AnswerComposer | None = None,
        acquisition: DataAcquisitionService | None = None,
        visualization_builder: VisualizationBuilder | None = None,
    ) -> None:
        self._provider = feature_provider
        self._features = feature_registry
        self._profiles = profile_registry
        self._planner = planner or DeterministicCopilotPlanner()
        self._decomposer = decomposer or DeterministicQueryDecomposer()
        self._observation_tools = observation_tools
        self._acquisition = acquisition
        self._visualizations = visualization_builder or VisualizationBuilder()
        deterministic_composer = DeterministicAnswerComposer()
        self._answer_composer: AnswerComposer = (
            FallbackAnswerComposer(answer_composer, deterministic_composer)
            if answer_composer is not None
            else deterministic_composer
        )
        self._capabilities = capabilities or default_decision_capabilities()
        if capabilities is None and observation_tools is not None:
            register_observation_capabilities(self._capabilities)
        if capabilities is None and acquisition is not None:
            register_acquisition_capabilities(self._capabilities)
        self._router = SmartToolRouter(self._capabilities)
        self._scorer = DecisionScoringEngine(feature_registry)

    def list_capabilities(self) -> tuple[ToolCapability, ...]:
        """Expose the exact tools the router may select in this runtime."""

        return self._capabilities.list()

    async def answer(
        self,
        question: str,
        *,
        entity_ids: Iterable[str] = (),
        min_quality_score: float = 0.0,
    ) -> CopilotResponse:
        """Answer a supported location question only from retrieved evidence."""

        now = datetime.now(UTC)
        requested_entities = tuple(dict.fromkeys(entity_ids))
        decomposition = await self._decomposer.decompose(question, requested_entities)
        routed_plan = self._router.route(decomposition)
        intent = await self._planner.plan(question, requested_entities)
        trace = [
            ToolTrace(
                tool="query_decomposer",
                outcome="clarification" if decomposition.needs_clarification else "decomposed",
                summary=(
                    f"{decomposition.objective}: "
                    f"{', '.join(item.value for item in decomposition.operations)}"
                ),
            )
        ]
        if intent is None:
            missing_capabilities = tuple(item.value for item in routed_plan.missing_operations)
            if decomposition.needs_clarification:
                answer = decomposition.clarification_question or "Please clarify the analysis goal."
                response_status = CopilotStatus.UNSUPPORTED_QUESTION
                response_warnings = ("No data tool was executed before clarification.",)
            elif missing_capabilities:
                answer = (
                    "I understood the requested analysis, but this runtime is missing the "
                    f"following validated capabilities: {', '.join(missing_capabilities)}."
                )
                response_status = CopilotStatus.INSUFFICIENT_DATA
                response_warnings = (
                    "The router failed closed; no partial conclusion was produced.",
                )
            elif (
                self._observation_tools is not None
                and AnalysisOperation.INSPECT_DATASET in decomposition.operations
            ):
                return await self._answer_observations(
                    now,
                    decomposition,
                    routed_plan,
                    trace,
                    min_quality_score=min_quality_score,
                )
            else:
                answer = "No registered decision profile can safely execute this question."
                response_status = CopilotStatus.UNSUPPORTED_QUESTION
                response_warnings = ("No data query or ranking was executed.",)
            return CopilotResponse(
                status=response_status,
                answer=answer,
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=response_warnings,
            )

        if not routed_plan.executable:
            missing_summary = ", ".join(item.value for item in routed_plan.missing_operations)
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=(
                    f"The validated plan cannot run because tools are missing: {missing_summary}."
                ),
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No data query or ranking was executed.",),
            )

        profile = self._profiles.get(intent.profile_code)
        feature_codes = tuple(
            dict.fromkeys(
                [
                    *(criterion.feature_code for criterion in profile.criteria),
                    *(constraint.feature_code for constraint in profile.constraints),
                ]
            )
        )
        plan = DecisionExecutionPlan(
            profile_code=profile.profile_code,
            profile_version=profile.version,
            feature_codes=feature_codes,
            entity_ids=intent.entity_ids,
            min_quality_score=min_quality_score,
        )
        trace.append(
            ToolTrace(
                tool="search_catalog",
                outcome="ok",
                summary=(
                    f"resolved {profile.profile_code}@{profile.version} and "
                    f"{len(feature_codes)} versioned feature contracts"
                ),
            )
        )
        for code in feature_codes:
            self._features.get(code)
        try:
            feature_set = self._provider.get_features(
                FeatureQuery(
                    feature_codes=feature_codes,
                    entity_ids=intent.entity_ids,
                    min_quality_score=min_quality_score,
                )
            )
        except (QueryExecutionError, KeyError, ValueError) as exc:
            trace.append(
                ToolTrace(tool="get_features", outcome="unavailable", summary=str(exc)[:300])
            )
            return self._insufficient(
                now,
                plan,
                trace,
                (str(exc),),
                decomposition=decomposition,
                routed_plan=routed_plan,
            )
        trace.append(
            ToolTrace(
                tool="get_features",
                outcome="ok",
                summary=f"retrieved {len(feature_set.values)} grounded feature values",
            )
        )
        if not feature_set.values:
            return self._insufficient(
                now,
                plan,
                trace,
                ("No published feature values satisfy the requested scope and quality.",),
                decomposition=decomposition,
                routed_plan=routed_plan,
            )

        citations, citation_lookup = _citations(feature_set.values)
        try:
            result = self._scorer.score(profile, feature_set.as_candidates())
        except ValueError as exc:
            trace.append(ToolTrace(tool="rank_candidates", outcome="blocked", summary=str(exc)))
            return self._insufficient(
                now,
                plan,
                trace,
                (str(exc),),
                decomposition=decomposition,
                routed_plan=routed_plan,
                citations=citations,
            )
        trace.append(
            ToolTrace(
                tool="rank_candidates",
                outcome="ok",
                summary=f"evaluated {len(result.candidates)} candidates deterministically",
            )
        )
        trace.append(
            ToolTrace(
                tool="explain_lineage",
                outcome="ok",
                summary=f"attached {len(citations)} dataset-version citations",
            )
        )
        candidates = _candidate_insights(result.candidates, citation_lookup)
        eligible = [candidate for candidate in candidates if candidate.eligible]
        warnings: list[str] = []
        if feature_set.truncated:
            warnings.append("Feature retrieval was truncated; the ranking may be incomplete.")
        if not eligible:
            warnings.append("No candidate has every required feature and constraint.")
            return self._insufficient(
                now,
                plan,
                trace,
                tuple(warnings),
                decomposition=decomposition,
                routed_plan=routed_plan,
                candidates=candidates,
                citations=citations,
            )
        top = eligible[0]
        fallback_answer = (
            f"{top.entity_name or top.entity_id} ranks first for "
            f"{profile.display_name} with a deterministic score of {top.score:.1f}/100. "
            "Review the feature contributions and cited dataset versions before making a decision."
        )
        answer = await self._compose_answer(
            AnswerCompositionContext(
                question=question,
                analysis_type="decision",
                grounded_facts_json=_grounded_json(
                    {
                        "profile_code": profile.profile_code,
                        "profile_version": profile.version,
                        "profile_name": profile.display_name,
                        "top_candidate": top.model_dump(mode="json"),
                        "candidate_count": len(candidates),
                        "citations": [item.model_dump(mode="json") for item in citations],
                    }
                ),
                allowed_citation_ids=tuple(item.citation_id for item in citations),
                fallback_answer=fallback_answer,
            ),
            trace,
        )
        visualizations = self._visualizations.decision(
            question,
            candidates,
            tuple(item.citation_id for item in citations),
        )
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            plan=plan,
            candidates=candidates,
            citations=citations,
            tool_trace=tuple(trace),
            assumptions=(
                f"Weights and constraints come from {profile.profile_code}@{profile.version}.",
                "Scores compare only the candidates present in the retrieved feature snapshot.",
            ),
            warnings=tuple(warnings),
            visualizations=visualizations,
        )

    async def _answer_observations(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        min_quality_score: float,
    ) -> CopilotResponse:
        tools = self._observation_tools
        if tools is None:  # Defensive: callers enter only when the suite is configured.
            raise RuntimeError("observation tools are unavailable")
        try:
            inspection = tools.inspect_dataset.execute(
                decomposition, min_quality_score=min_quality_score
            )
            metadata = tools.catalog.get(inspection.dataset_id)
            if metadata.version != inspection.dataset_version:
                raise QueryExecutionError("the published dataset version changed during analysis")
        except YouthCompassError as exc:
            trace.append(
                ToolTrace(tool="inspect_dataset", outcome="unavailable", summary=str(exc)[:300])
            )
            return self._observation_failure(
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
        if AnalysisOperation.QUERY_OBSERVATIONS not in decomposition.operations:
            fallback_answer = (
                f"{inspection.dataset_id}@{inspection.dataset_version} contains "
                f"{inspection.metric_code} from {inspection.period_start} to "
                f"{inspection.period_end} across {inspection.entity_count} entities."
            )
            answer = await self._compose_answer(
                AnswerCompositionContext(
                    question=decomposition.original_question,
                    analysis_type="dataset_inspection",
                    grounded_facts_json=_grounded_json(inspection.model_dump(mode="json")),
                    fallback_answer=fallback_answer,
                ),
                trace,
            )
            visualizations = self._visualizations.inspection(
                decomposition.original_question, inspection
            )
            self._trace_visualizations(trace, visualizations)
            return CopilotResponse(
                status=CopilotStatus.ANSWERED,
                answer=answer,
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                dataset_inspection=inspection,
                tool_trace=tuple(trace),
                visualizations=visualizations,
            )
        try:
            series = tools.query_observations.execute(decomposition, inspection, metadata)
        except YouthCompassError as exc:
            trace.append(
                ToolTrace(tool="query_observations", outcome="unavailable", summary=str(exc)[:300])
            )
            return self._observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning=str(exc),
                inspection=inspection,
            )
        trace.append(
            ToolTrace(
                tool="query_observations",
                outcome="ok",
                summary=f"retrieved {len(series.points)} aggregated observations",
            )
        )
        comparison = None
        if AnalysisOperation.COMPARE_ENTITIES in decomposition.operations:
            try:
                comparison = tools.compare_entities.execute(series)
            except YouthCompassError as exc:
                trace.append(
                    ToolTrace(
                        tool="compare_entities", outcome="unavailable", summary=str(exc)[:300]
                    )
                )
                return self._observation_failure(
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
        citation = EvidenceCitation(
            citation_id="data-1",
            dataset_id=metadata.dataset_id,
            dataset_version=metadata.version,
            quality_score=metadata.quality_score,
            retrieved_at=metadata.published_at or metadata.created_at,
        )
        if AnalysisOperation.EXPLAIN_LINEAGE in decomposition.operations:
            trace.append(
                ToolTrace(
                    tool="explain_lineage",
                    outcome="ok",
                    summary="attached 1 dataset-version citation",
                )
            )
        fallback_answer = _observation_answer(series, comparison)
        answer = await self._compose_answer(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="observation_comparison",
                grounded_facts_json=_grounded_json(
                    {
                        "dataset_inspection": inspection.model_dump(mode="json"),
                        "observation_series": series.model_dump(mode="json"),
                        "comparison": (comparison.model_dump(mode="json") if comparison else None),
                        "citation": citation.model_dump(mode="json"),
                    }
                ),
                allowed_citation_ids=(citation.citation_id,),
                fallback_answer=fallback_answer,
            ),
            trace,
        )
        visualizations = self._visualizations.observations(
            decomposition.original_question,
            series,
            comparison,
            (citation.citation_id,),
        )
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            dataset_inspection=inspection,
            observation_series=series,
            comparison=comparison,
            citations=(citation,),
            tool_trace=tuple(trace),
            assumptions=(
                "Canonical rows sharing an entity, period, metric, unit, and scope are summed.",
                "Changes compare the first and last observations in the requested period.",
            ),
            visualizations=visualizations,
        )

    def _observation_failure(
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
        requirement, source_candidates = self._discover_sources(decomposition, trace)
        visualizations = self._visualizations.sources(
            decomposition.original_question, source_candidates
        )
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=(
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            ),
            answer=_data_gap_answer(
                decomposition.original_question,
                source_candidates,
                "There is not enough compatible observation data for this analysis.",
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            dataset_inspection=inspection,
            observation_series=series,
            tool_trace=tuple(trace),
            warnings=(warning,),
            data_requirement=requirement,
            source_candidates=source_candidates,
            visualizations=visualizations,
        )

    async def _compose_answer(
        self, context: AnswerCompositionContext, trace: list[ToolTrace]
    ) -> str:
        result = await self._answer_composer.compose(context)
        trace.append(
            ToolTrace(
                tool="answer_composer",
                outcome=result.mode,
                summary=(f"composed grounded narrative with {len(result.citation_ids)} citations"),
            )
        )
        return result.answer

    def _insufficient(
        self,
        now: datetime,
        plan: DecisionExecutionPlan,
        trace: list[ToolTrace],
        warnings: tuple[str, ...],
        *,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        candidates: tuple[CandidateInsight, ...] = (),
        citations: tuple[EvidenceCitation, ...] = (),
    ) -> CopilotResponse:
        requirement, source_candidates = self._discover_sources(
            decomposition, trace, metric_codes=plan.feature_codes
        )
        visualizations = (
            self._visualizations.sources(decomposition.original_question, source_candidates)
            if source_candidates
            else self._visualizations.decision(
                decomposition.original_question,
                candidates,
                tuple(item.citation_id for item in citations),
            )
        )
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=(
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            ),
            answer=_data_gap_answer(
                decomposition.original_question,
                source_candidates,
                "There is not enough validated feature data to produce a grounded ranking.",
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            plan=plan,
            candidates=candidates,
            citations=citations,
            tool_trace=tuple(trace),
            warnings=warnings,
            data_requirement=requirement,
            source_candidates=source_candidates,
            visualizations=visualizations,
        )

    @staticmethod
    def _trace_visualizations(
        trace: list[ToolTrace], visualizations: tuple[VisualizationSpec, ...]
    ) -> None:
        if visualizations:
            trace.append(
                ToolTrace(
                    tool="visualization_builder",
                    outcome="ok",
                    summary=f"built {len(visualizations)} grounded visualization specs",
                )
            )

    def _discover_sources(
        self,
        decomposition: DecomposedQuery,
        trace: list[ToolTrace],
        *,
        metric_codes: tuple[str, ...] = (),
    ) -> tuple[DataRequirement, tuple[SourceCandidate, ...]]:
        requirement = DataRequirement(
            topic_terms=decomposition.subject_terms,
            metric_codes=metric_codes or decomposition.metric_terms,
            entity_ids=decomposition.entity_ids,
            time_expression=decomposition.time_expression,
        )
        if self._acquisition is None:
            return requirement, ()
        try:
            candidates = self._acquisition.discover(requirement)
        except SourceAcquisitionError as exc:
            trace.append(
                ToolTrace(tool="discover_sources", outcome="failed", summary=str(exc)[:300])
            )
            return requirement, ()
        trace.append(
            ToolTrace(
                tool="discover_sources",
                outcome="candidates" if candidates else "no_match",
                summary=f"found {len(candidates)} allowlisted source candidates",
            )
        )
        return requirement, candidates


def _citations(
    values: tuple[FeatureValue, ...],
) -> tuple[tuple[EvidenceCitation, ...], dict[tuple[str, str, str], str]]:
    evidence_by_key = {
        (item.dataset_id, item.dataset_version, item.source_uri): item
        for value in values
        for item in value.evidence
    }
    lookup: dict[tuple[str, str, str], str] = {}
    citations: list[EvidenceCitation] = []
    for index, key in enumerate(sorted(evidence_by_key), start=1):
        item = evidence_by_key[key]
        citation_id = f"data-{index}"
        lookup[key] = citation_id
        citations.append(
            EvidenceCitation(
                citation_id=citation_id,
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                quality_score=item.quality_score,
                retrieved_at=item.retrieved_at,
            )
        )
    return tuple(citations), lookup


def _data_gap_answer(
    question: str,
    source_candidates: tuple[SourceCandidate, ...],
    fallback: str,
) -> str:
    if not source_candidates:
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


def _candidate_insights(
    candidates: tuple[CandidateScore, ...],
    citation_lookup: dict[tuple[str, str, str], str],
) -> tuple[CandidateInsight, ...]:
    rank = 0
    results: list[CandidateInsight] = []
    for candidate in candidates:
        candidate_rank = None
        if candidate.eligible:
            rank += 1
            candidate_rank = rank
        results.append(
            CandidateInsight(
                rank=candidate_rank,
                entity_id=candidate.entity_id,
                entity_name=candidate.entity_name,
                eligible=candidate.eligible,
                score=candidate.score,
                contributions=tuple(
                    FeatureContributionInsight(
                        feature_code=contribution.feature_code,
                        raw_value=contribution.raw_value,
                        effective_weight=contribution.effective_weight,
                        points=contribution.points,
                        citations=tuple(
                            citation_lookup[
                                (item.dataset_id, item.dataset_version, item.source_uri)
                            ]
                            for item in contribution.evidence
                        ),
                    )
                    for contribution in candidate.contributions
                ),
                failed_constraints=candidate.failed_constraints,
                missing_required_features=candidate.missing_required_features,
            )
        )
    return tuple(results)


def _observation_answer(series: ObservationSeries, comparison: EntityComparison | None) -> str:
    if comparison is None:
        return f"Retrieved {len(series.points)} grounded observations for {series.metric_code}."
    summaries = []
    for change in comparison.changes[:5]:
        name = change.entity_name or change.entity_id
        delta = (
            f"{change.percent_change:+.2f}%"
            if change.percent_change is not None
            else f"{change.absolute_change:+g} {series.unit_code}"
        )
        summaries.append(
            f"{name} {change.direction} from {change.first_value:g} to "
            f"{change.last_value:g} ({delta})"
        )
    return (
        f"For {series.metric_code}, " + "; ".join(summaries) + ". "
        "Values come from the cited published dataset version."
    )


def _grounded_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
