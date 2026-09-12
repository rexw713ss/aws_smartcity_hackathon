"""Deterministic, evidence-grounded copilot orchestration."""

import json
import logging
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
    AnalysisFilters,
    AnalysisOperation,
    AnswerCompositionContext,
    CandidateInsight,
    ConversationContext,
    CopilotIntent,
    CopilotResponse,
    CopilotStatus,
    DataLimitations,
    DatasetInspection,
    DecisionExecutionPlan,
    DecomposedQuery,
    EntityComparison,
    EvidenceCitation,
    EvidenceExcerptRow,
    FeatureContributionInsight,
    ImpactAnalysis,
    ImpactDataGap,
    ImpactFinding,
    JoinedObservationRow,
    MultiDatasetAnalysis,
    ObservationPoint,
    ObservationSeries,
    RoutedToolPlan,
    ToolCapability,
    ToolTrace,
    VisualizationColumn,
    VisualizationEncoding,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.conversation import (
    ConversationContextResolver,
    ConversationContextStore,
    context_from_decomposition,
    new_session_id,
)
from youth_compass.agent.limitations import DataLimitationsBuilder
from youth_compass.agent.observation_tools import ObservationToolSuite
from youth_compass.agent.planning import (
    DeterministicQueryDecomposer,
    QueryDecomposer,
    SmartToolRouter,
    ToolCapabilityRegistry,
    default_decision_capabilities,
    register_acquisition_capabilities,
    register_forecast_capabilities,
    register_impact_capabilities,
    register_observation_capabilities,
)
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.decisioning import (
    AnalysisInput,
    AnalysisJoin,
    AnalysisPlan,
    AnalysisPlanValidator,
    CandidateScore,
    DecisionProfileRegistry,
    DecisionScoringEngine,
    FeatureProvider,
    FeatureQuery,
    FeatureRegistry,
    FeatureValue,
    JoinCardinality,
    PopulationBalanceMode,
    ScenarioAdjustment,
    ScenarioOperation,
    YouthPopulationScenarioResult,
    YouthPopulationScenarioService,
)
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import (
    ModelInvocationError,
    QueryExecutionError,
    SourceAcquisitionError,
    YouthCompassError,
)
from youth_compass.ontology import (
    NameLanguage,
    extract_districts,
    extract_topics,
    humanize_code,
    question_language,
    readable_entity_name,
    readable_feature_name,
    resolve_district_name,
    resolve_topic_name,
)
from youth_compass.ports import (
    DataRequirement,
    ForecastRequest,
    ForecastResult,
    ForecastService,
    ModelProvider,
    ModelRequest,
    SourceCandidate,
)

_LOGGER = logging.getLogger(__name__)


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
        forecast_service: ForecastService | None = None,
        answer_composer: AnswerComposer | None = None,
        acquisition: DataAcquisitionService | None = None,
        visualization_builder: VisualizationBuilder | None = None,
        conversation_store: ConversationContextStore | None = None,
        conversation_resolver: ConversationContextResolver | None = None,
        scenario_service: YouthPopulationScenarioService | None = None,
    ) -> None:
        self._provider = feature_provider
        self._features = feature_registry
        self._profiles = profile_registry
        self._planner = planner or DeterministicCopilotPlanner()
        self._decomposer = decomposer or DeterministicQueryDecomposer()
        self._observation_tools = observation_tools
        self._forecast_service = forecast_service
        self._acquisition = acquisition
        self._visualizations = visualization_builder or VisualizationBuilder()
        self._limitations = DataLimitationsBuilder()
        self._conversation_store = conversation_store
        self._conversation_resolver = conversation_resolver or ConversationContextResolver()
        self._scenario_service = scenario_service
        deterministic_composer = DeterministicAnswerComposer()
        self._answer_composer: AnswerComposer = (
            FallbackAnswerComposer(answer_composer, deterministic_composer)
            if answer_composer is not None
            else deterministic_composer
        )
        self._capabilities = capabilities or default_decision_capabilities()
        if capabilities is None and observation_tools is not None:
            register_observation_capabilities(self._capabilities)
        if capabilities is None and forecast_service is not None:
            register_forecast_capabilities(self._capabilities)
        if capabilities is None and acquisition is not None:
            register_acquisition_capabilities(self._capabilities)
        if capabilities is None and scenario_service is not None:
            register_impact_capabilities(self._capabilities)
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
        session_id: str | None = None,
    ) -> CopilotResponse:
        """Resolve structured follow-up context, then execute one grounded turn."""

        now = datetime.now(UTC)
        requested_entities = tuple(dict.fromkeys(entity_ids))
        active_session_id = session_id
        previous = None
        if self._conversation_store is not None:
            active_session_id = active_session_id or new_session_id()
            previous = self._read_context(active_session_id)
        initial = await self._decomposer.decompose(question, requested_entities)
        # Scope from the question before session scope is applied: a district
        # the person just named must win over the one carried by the session.
        initial, question_scope = _scope_from_question(question, initial)
        decomposition, context_applied = self._conversation_resolver.resolve(
            question, initial, previous
        )
        response = await self._execute(
            question,
            now=now,
            requested_entities=decomposition.entity_ids,
            min_quality_score=min_quality_score,
            decomposition=decomposition,
            context_applied=context_applied,
            question_scope=question_scope,
        )
        # Only a scope that actually produced an answer is remembered. A scope
        # that found no evidence would otherwise be inherited by every later
        # turn, leaving the session permanently unable to answer anything.
        if (
            self._conversation_store is not None
            and active_session_id is not None
            and response.status is CopilotStatus.ANSWERED
        ):
            self._write_context(
                context_from_decomposition(active_session_id, decomposition, now, previous)
            )
        return response.model_copy(update={"session_id": active_session_id})

    def _read_context(self, session_id: str) -> ConversationContext | None:
        """Read session scope, treating a store failure as a first turn.

        A durable store is remote and can be unavailable. Losing inherited scope
        degrades a follow-up into a clarification request, which is recoverable;
        failing the request is not.
        """

        assert self._conversation_store is not None
        try:
            return self._conversation_store.get(session_id)
        except YouthCompassError as exc:
            _LOGGER.warning("conversation context unavailable for this turn: %s", exc)
            return None

    def _write_context(self, context: ConversationContext) -> None:
        """Persist session scope, never failing the answer already produced."""

        assert self._conversation_store is not None
        try:
            self._conversation_store.put(context)
        except YouthCompassError as exc:
            _LOGGER.warning("conversation context was not persisted: %s", exc)

    async def _execute(
        self,
        question: str,
        *,
        now: datetime,
        requested_entities: tuple[str, ...],
        min_quality_score: float,
        decomposition: DecomposedQuery,
        context_applied: bool,
        question_scope: tuple[str, ...] = (),
    ) -> CopilotResponse:
        """Execute one already-resolved decomposition without reading session state."""

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
        if AnalysisOperation.SEARCH_TOOLS in decomposition.operations:
            matched_tools = self._capabilities.search(decomposition.operations)
            trace.append(
                ToolTrace(
                    tool="search_tools",
                    outcome="ok",
                    summary="selected registered tools: "
                    + ", ".join(item.name for item in matched_tools),
                )
            )
        if question_scope:
            trace.append(
                ToolTrace(
                    tool="resolve_local_ontology",
                    outcome="ok",
                    summary="scoped to districts named in the question: "
                    + "; ".join(question_scope),
                )
            )
        if context_applied:
            trace.append(
                ToolTrace(
                    tool="conversation_context",
                    outcome="applied",
                    summary="filled omitted scope from the previous structured turn",
                )
            )
        if intent is None:
            if AnalysisOperation.SIMULATE_SCENARIO in decomposition.operations:
                return self._answer_impact_scenario(
                    now,
                    decomposition,
                    routed_plan,
                    trace,
                )
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

        citations, citation_lookup = _citations(feature_set.values, question)
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
        candidates = _candidate_insights(result.candidates, citation_lookup, question)
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
        fallback_answer = _decision_answer(
            question=question,
            profile_name=profile.display_name,
            candidates=tuple(eligible),
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
                        "ranked_candidates": [
                            item.model_dump(mode="json") for item in eligible[:3]
                        ],
                        "candidate_count": len(candidates),
                        # Row-level excerpts are for reader verification in the
                        # Evidence panel. Candidate facts already contain every
                        # value the composer may verbalize, so repeating the
                        # excerpts here only inflates the model prompt.
                        "citations": [
                            item.model_dump(mode="json", exclude={"excerpt"}) for item in citations
                        ],
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
        limitations = self._limitations.build(
            now=now,
            citations=citations,
            observed_entity_ids=[candidate.entity_id for candidate in candidates],
            # A location decision is scored over whichever candidates the
            # profile supplied, so the district set is not the denominator.
            requested_entity_ids=[candidate.entity_id for candidate in candidates],
            catalog_terms=plan.feature_codes,
        )
        self._trace_limitations(trace, limitations)
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
            limitations=limitations,
        )

    def _answer_impact_scenario(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
    ) -> CopilotResponse:
        """Run the grounded part of an impact chain and fail closed at data gaps."""

        if self._scenario_service is None:
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer="The population scenario engine is unavailable.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No scenario or impact estimate was produced.",),
            )
        if len(decomposition.entity_ids) != 1:
            return CopilotResponse(
                status=CopilotStatus.UNSUPPORTED_QUESTION,
                answer="Name exactly one New Taipei district for this impact scenario.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("The scenario was not run because its geography was ambiguous.",),
            )
        shock = _population_shock(decomposition.original_question)
        if shock is None:
            return CopilotResponse(
                status=CopilotStatus.UNSUPPORTED_QUESTION,
                answer="State the number of people entering or leaving the district.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("The scenario was not run because no population shock was found.",),
            )
        target_year = _scenario_target_year(decomposition.original_question) or 2030
        try:
            scenario = self._scenario_service.run(
                (
                    ScenarioAdjustment(
                        district_id=decomposition.entity_ids[0],
                        operation=ScenarioOperation.ABSOLUTE_CHANGE,
                        value=shock,
                    ),
                ),
                balance_mode=PopulationBalanceMode.OPEN,
                target_year=target_year,
            )
        except YouthCompassError as exc:
            trace.append(
                ToolTrace(tool="simulate_scenario", outcome="unavailable", summary=str(exc)[:300])
            )
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer="The requested population scenario could not be projected safely.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=(str(exc),),
            )
        district = next(
            row for row in scenario.rows if row.district_code == decomposition.entity_ids[0]
        )
        trace.append(
            ToolTrace(
                tool="simulate_scenario",
                outcome="ok",
                summary=(
                    f"projected ages 18-35 in {district.district_name} to {target_year}: "
                    f"{district.baseline_value:,} baseline, {district.scenario_value:,} scenario"
                ),
            )
        )
        gaps = _impact_data_gaps(decomposition.original_question)
        findings = (
            ImpactFinding(
                stage="population",
                label=f"Registered residents aged 18-35 in {district.district_name}",
                baseline_value=district.baseline_value,
                scenario_value=district.scenario_value,
                absolute_delta=district.absolute_delta,
                unit="persons",
                evidence_kind="derived",
            ),
        )
        impact = ImpactAnalysis(
            district_code=district.district_code,
            district_name=district.district_name,
            observed_period=scenario.observed_period,
            target_year=target_year,
            shock_people=shock,
            findings=findings,
            data_gaps=gaps,
            confidence="insufficient" if gaps else "medium",
        )
        if gaps:
            trace.append(
                ToolTrace(
                    tool="assess_capacity",
                    outcome="data_gap",
                    summary="; ".join(
                        f"{gap.domain}: {', '.join(gap.required_metrics)}" for gap in gaps
                    ),
                )
            )
            required_metrics = tuple(
                dict.fromkeys(metric for gap in gaps for metric in gap.required_metrics)
            )
            requirement, source_candidates = self._discover_sources(
                decomposition, trace, metric_codes=required_metrics
            )
            trace.append(
                ToolTrace(
                    tool="recommend_investment",
                    outcome="withheld",
                    summary=(
                        "capacity evidence is incomplete; no infrastructure ranking was produced"
                    ),
                )
            )
            answer = _impact_gap_answer(
                impact, bool(source_candidates), decomposition.original_question
            )
            status = (
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            )
        else:
            requirement, source_candidates = None, ()
            answer = _impact_population_answer(impact, decomposition.original_question)
            status = CopilotStatus.ANSWERED
        visualizations = _impact_visualizations(scenario, decomposition.original_question)
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=status,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            impact_analysis=impact,
            tool_trace=tuple(trace),
            assumptions=(
                f"The user-supplied population shock is {shock:+,} people by {target_year}.",
                "The population baseline ages observed single-year cohorts forward using "
                "recent district transition rates.",
            ),
            warnings=(
                "No housing, transport, or service impact is inferred without compatible "
                "capacity and demand data.",
                "The population scenario is not evidence that a policy caused migration.",
            ),
            data_requirement=requirement,
            source_candidates=source_candidates,
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

        requested_datasets = _explicit_catalog_datasets(
            decomposition.original_question,
            tools.catalog.list_datasets(),
        )
        if len(requested_datasets) > 1:
            return self._answer_multi_dataset_observations(
                now,
                decomposition,
                routed_plan,
                trace,
                requested_datasets,
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
        if AnalysisOperation.FORECAST_METRIC in decomposition.operations:
            return await self._answer_forecast(
                now,
                decomposition,
                routed_plan,
                trace,
                inspection,
                metadata,
            )
        if AnalysisOperation.QUERY_OBSERVATIONS not in decomposition.operations:
            fallback_answer = (
                f"{humanize_code(inspection.dataset_id)}@{inspection.dataset_version} contains "
                f"{humanize_code(inspection.metric_code)} from {inspection.period_start} to "
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
            excerpt=tuple(
                EvidenceExcerptRow(
                    entity_id=point.entity_id,
                    entity_name=point.entity_name
                    or readable_entity_name(
                        point.entity_id,
                        None,
                        _name_language(decomposition.original_question),
                    ),
                    metric_code=series.metric_code,
                    metric_name=humanize_code(series.metric_code),
                    value=point.value,
                    period=point.period,
                )
                for point in series.points[:100]
            ),
        )
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
                        "applied_filters": decomposition.filters.model_dump(mode="json"),
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
        limitations = self._limitations.build(
            now=now,
            citations=(citation,),
            observed_entity_ids=[point.entity_id for point in series.points],
            requested_entity_ids=decomposition.entity_ids,
            catalog_terms=_catalog_terms(inspection, metadata),
            series=series,
        )
        self._trace_limitations(trace, limitations)
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

        assert self._observation_tools is not None
        records = tuple(
            sorted(
                (
                    item
                    for item in self._observation_tools.catalog.list_datasets()
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
            return self._observation_failure(
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
        self._trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            citations=citations,
            tool_trace=tuple(trace),
            visualizations=visualizations,
        )

    def _answer_multi_dataset_observations(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        datasets: tuple[DatasetMetadata, ...],
        *,
        min_quality_score: float,
    ) -> CopilotResponse:
        """Query several tables and inner-join exact canonical entity-period rows."""

        assert self._observation_tools is not None
        tools = self._observation_tools
        unavailable = tuple(
            item.dataset_id
            for item in datasets
            if item.status is not DatasetStatus.PUBLISHED or item.quality_score < min_quality_score
        )
        if unavailable:
            names = ", ".join(unavailable)
            trace.append(
                ToolTrace(
                    tool="validate_dataset_scope",
                    outcome="unavailable",
                    summary=(
                        f"requested datasets are not published at the required quality: {names}"
                    ),
                )
            )
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=(
                    f"I cannot combine the requested data because {names} is not currently "
                    "published at the required quality. No partial answer was produced."
                ),
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=(
                    "Every requested dataset must be published before a multi-dataset join runs.",
                ),
            )

        inspections: list[DatasetInspection] = []
        series_by_dataset: list[tuple[DatasetMetadata, ObservationSeries]] = []
        try:
            for metadata in datasets:
                inspection = tools.inspect_dataset.execute_for_dataset(
                    decomposition,
                    metadata.dataset_id,
                    min_quality_score=min_quality_score,
                )
                current = tools.catalog.get(metadata.dataset_id)
                if current.version != inspection.dataset_version:
                    raise QueryExecutionError(
                        f"published dataset {metadata.dataset_id!r} changed during analysis"
                    )
                series = tools.query_observations.execute(decomposition, inspection, current)
                inspections.append(inspection)
                series_by_dataset.append((current, series))
                trace.extend(
                    (
                        ToolTrace(
                            tool="inspect_dataset",
                            outcome="ok",
                            summary=(
                                f"resolved {metadata.dataset_id}@{inspection.dataset_version} "
                                f"metric {inspection.metric_code}"
                            ),
                        ),
                        ToolTrace(
                            tool="query_observations",
                            outcome="ok",
                            summary=(
                                f"retrieved {len(series.points)} aggregated observations from "
                                f"{metadata.dataset_id}"
                            ),
                        ),
                    )
                )
        except YouthCompassError as exc:
            trace.append(
                ToolTrace(
                    tool="query_observations",
                    outcome="unavailable",
                    summary=str(exc)[:300],
                )
            )
            return self._observation_failure(
                now,
                decomposition,
                routed_plan,
                trace,
                warning=str(exc),
            )

        aliases = tuple(f"source_{index}" for index in range(1, len(datasets) + 1))
        metric_fields = tuple(
            f"{alias}_{inspection.metric_code}"
            for alias, inspection in zip(aliases, inspections, strict=True)
        )
        analysis_plan = AnalysisPlan(
            inputs=tuple(
                AnalysisInput(
                    alias=alias,
                    dataset_id=metadata.dataset_id,
                    dataset_version=metadata.version,
                    dimensions=("entity_id", "period"),
                    metrics=(metric_field,),
                    grain=("entity_id", "period"),
                )
                for alias, metric_field, (metadata, _) in zip(
                    aliases, metric_fields, series_by_dataset, strict=True
                )
            ),
            joins=tuple(
                AnalysisJoin(
                    left_alias=aliases[0],
                    right_alias=alias,
                    keys=("entity_id", "period"),
                    cardinality=JoinCardinality.ONE_TO_ONE,
                )
                for alias in aliases[1:]
            ),
            output_dimensions=("entity_id", "period"),
            output_metrics=metric_fields,
            max_rows=10_000,
        )
        validation = AnalysisPlanValidator().validate(analysis_plan)
        if not validation.valid:
            reasons = "; ".join(issue.message for issue in validation.issues)
            trace.append(
                ToolTrace(tool="validate_analysis_plan", outcome="blocked", summary=reasons[:300])
            )
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer="The requested datasets cannot be joined safely at their validated grain.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=(reasons,),
            )
        trace.append(
            ToolTrace(
                tool="validate_analysis_plan",
                outcome="ok",
                summary="validated one-to-one join on canonical entity_id and period",
            )
        )

        # Inputs published at different granularities cannot share an exact
        # period key. The finer one is collapsed to each year's closing month,
        # which the answer states, because that reading is only correct for a
        # point-in-time count.
        series_by_dataset, alignment_notes = _align_period_granularity(series_by_dataset)
        if alignment_notes:
            trace.append(
                ToolTrace(
                    tool="align_period_granularity",
                    outcome="ok",
                    summary="; ".join(alignment_notes)[:300],
                )
            )

        point_maps = [
            {
                _joined_observation_key(point.entity_id, point.period): point
                for point in series.points
            }
            for _, series in series_by_dataset
        ]
        common_keys = set.intersection(*(set(points) for points in point_maps))
        if not common_keys:
            # "No overlap" has two very different causes and the reader has to
            # know which one they hit: a genuine gap in coverage is a data
            # problem, whereas a granularity mismatch is a modelling decision
            # this executor refuses to make on its own.
            reason, diagnosis = _no_overlap_reason(series_by_dataset)
            trace.append(
                ToolTrace(tool="join_observations", outcome="unavailable", summary=reason[:300])
            )
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=diagnosis,
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=(reason,),
            )

        ordered_keys = sorted(common_keys, key=lambda key: (key[1], key[0]))
        truncated = len(ordered_keys) > analysis_plan.max_rows
        ordered_keys = ordered_keys[: analysis_plan.max_rows]
        joined_rows = tuple(
            JoinedObservationRow(
                entity_id=key[0],
                entity_name=next(
                    (points[key].entity_name for points in point_maps if points[key].entity_name),
                    None,
                ),
                period=key[1],
                values={
                    metadata.dataset_id: points[key].value
                    for (metadata, _), points in zip(series_by_dataset, point_maps, strict=True)
                },
            )
            for key in ordered_keys
        )
        analysis = MultiDatasetAnalysis(
            dataset_metrics={
                metadata.dataset_id: series.metric_code for metadata, series in series_by_dataset
            },
            rows=joined_rows,
        )
        trace.append(
            ToolTrace(
                tool="join_observations",
                outcome="ok",
                summary=f"joined {len(joined_rows)} exact entity-period rows",
            )
        )

        citations = tuple(
            EvidenceCitation(
                citation_id=f"data-{index}",
                dataset_id=metadata.dataset_id,
                dataset_version=metadata.version,
                quality_score=metadata.quality_score,
                retrieved_at=metadata.published_at or metadata.created_at,
                excerpt=tuple(
                    EvidenceExcerptRow(
                        entity_id=point.entity_id,
                        entity_name=point.entity_name
                        or readable_entity_name(
                            point.entity_id,
                            None,
                            _name_language(decomposition.original_question),
                        ),
                        metric_code=series.metric_code,
                        metric_name=humanize_code(series.metric_code),
                        value=point.value,
                        period=point.period,
                    )
                    for point in series.points[:100]
                ),
            )
            for index, (metadata, series) in enumerate(series_by_dataset, start=1)
        )
        if AnalysisOperation.EXPLAIN_LINEAGE in decomposition.operations:
            trace.append(
                ToolTrace(
                    tool="explain_lineage",
                    outcome="ok",
                    summary=f"attached {len(citations)} dataset-version citations",
                )
            )

        latest_period = max(row.period for row in joined_rows)
        latest_rows = [row for row in joined_rows if row.period == latest_period]
        citation_suffix = " ".join(f"[{item.citation_id}]" for item in citations)
        bullets = []
        for row in latest_rows[:10]:
            name = readable_entity_name(
                row.entity_id,
                row.entity_name,
                _name_language(decomposition.original_question),
            )
            values = "; ".join(
                # .10g keeps grouping without collapsing a six-figure count
                # into scientific notation, which .4g did.
                f"{humanize_code(analysis.dataset_metrics[dataset_id])}: {value:,.10g}"
                for dataset_id, value in row.values.items()
            )
            bullets.append(f"- {name} — {values} {citation_suffix}")
        answer = (
            f"Combined {len(datasets)} published datasets using an exact district-and-period "
            f"join. The latest common period is {latest_period}:\n\n" + "\n".join(bullets)
        )
        if len(latest_rows) > len(bullets):
            answer += (
                f"\n\nShowing 10 of {len(latest_rows)} matching locations; the table has the rest."
            )
        # A reader comparing two columns must be told when one of them was moved
        # onto the other's calendar, and which reading that makes valid.
        for note in alignment_notes:
            answer += f"\n\nNote: {note}."
        scopes = {series.population_scope for _, series in series_by_dataset}
        if len(scopes) > 1:
            answer += (
                "\n\nNote: these datasets count different populations ("
                + ", ".join(sorted(scopes))
                + "), so the columns are not two measurements of the same group."
            )

        columns = [
            VisualizationColumn(field="entity_name", label="District"),
            VisualizationColumn(field="period", label="Period"),
        ]
        for index, (_, series) in enumerate(series_by_dataset, start=1):
            columns.append(
                VisualizationColumn(
                    field=f"metric_{index}",
                    label=humanize_code(series.metric_code),
                    unit=series.unit_code,
                )
            )
        table_rows: list[dict[str, str | int | float | bool | None]] = []
        for row in latest_rows[:200]:
            table_row: dict[str, str | int | float | bool | None] = {
                "entity_name": row.entity_name or row.entity_id,
                "period": row.period,
            }
            for index, (dataset_id, value) in enumerate(row.values.items(), start=1):
                del dataset_id
                table_row[f"metric_{index}"] = value
            table_rows.append(table_row)
        visualizations = (
            VisualizationSpec(
                visualization_id="multi-dataset-comparison",
                type=VisualizationType.DATA_TABLE,
                title=f"Multi-dataset comparison · {latest_period}",
                description="Exact inner join on canonical district identity and reporting period.",
                columns=tuple(columns),
                rows=tuple(table_rows),
                citation_ids=tuple(item.citation_id for item in citations),
                truncated=truncated or len(latest_rows) > 200,
            ),
        )
        self._trace_visualizations(trace, visualizations)
        limitations = self._limitations.build(
            now=now,
            citations=citations,
            observed_entity_ids=(row.entity_id for row in latest_rows),
            requested_entity_ids=decomposition.entity_ids,
            catalog_terms=tuple(
                term
                for metadata, series in series_by_dataset
                for term in (metadata.topic, metadata.dataset_id, series.metric_code)
            ),
        )
        self._trace_limitations(trace, limitations)
        warnings = (
            ("The joined result exceeded 10000 rows and was truncated.",) if truncated else ()
        )
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            multi_dataset_analysis=analysis,
            citations=citations,
            tool_trace=tuple(trace),
            assumptions=(
                "Each source is aggregated independently before joining.",
                "Only exact canonical district and reporting-period matches are included.",
            ),
            warnings=warnings,
            visualizations=visualizations,
            limitations=limitations,
        )

    async def _answer_forecast(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        inspection: DatasetInspection,
        metadata: DatasetMetadata,
    ) -> CopilotResponse:
        service = self._forecast_service
        if service is None:
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
            trace.append(
                ToolTrace(tool="forecast_metric", outcome="unavailable", summary=str(exc)[:300])
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
        answer = await self._compose_answer(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="forecast",
                grounded_facts_json=_grounded_json(
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
        )
        visualizations = self._visualizations.forecast(
            decomposition.original_question,
            result,
            (citation.citation_id,),
        )
        self._trace_visualizations(trace, visualizations)
        limitations = self._limitations.build(
            now=now,
            citations=(citation,),
            observed_entity_ids=[point.district_code for point in result.points],
            requested_entity_ids=decomposition.entity_ids,
            catalog_terms=_catalog_terms(inspection, metadata),
        )
        self._trace_limitations(trace, limitations)
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            dataset_inspection=inspection,
            forecast_result=result,
            citations=(citation,),
            tool_trace=tuple(trace),
            assumptions=(
                "Forecast points come from the latest published model available as of the request.",
                "Intervals describe model uncertainty and are not guaranteed outcomes.",
            ),
            warnings=("The forecast is predictive, not evidence of policy causation.",),
            visualizations=visualizations,
            limitations=limitations,
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
    def _trace_limitations(trace: list[ToolTrace], limitations: DataLimitations) -> None:
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

    @staticmethod
    def _trace_visualizations(
        trace: list[ToolTrace], visualizations: tuple[VisualizationSpec, ...]
    ) -> None:
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


def _scope_from_question(
    question: str, decomposition: DecomposedQuery
) -> tuple[DecomposedQuery, tuple[str, ...]]:
    """Narrow an analysis to the districts the question itself names.

    Entity identifiers reach this service only as an API parameter, so a person
    who writes "the trend in Sanxia District" would otherwise be answered about
    all 29 districts. Reading the place out of the question is what makes the
    typed question and the typed parameter equivalent.

    Two cases are deliberately left alone. An explicit parameter always wins,
    because a caller that named entities meant those. A decision plan is never
    narrowed: it ranks the candidates its profile defines, which are sites and
    slugs rather than districts, so a district code would empty the ranking.
    """

    if decomposition.entity_ids or AnalysisOperation.RANK_CANDIDATES in decomposition.operations:
        return decomposition, ()
    districts = extract_districts(question)
    if not districts:
        return decomposition, ()
    scope = tuple(district.code for district in districts)
    named = tuple(f"{district.code} {district.name}" for district in districts)
    return decomposition.model_copy(update={"entity_ids": scope}), named


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


def _explicit_catalog_datasets(
    question: str, records: Iterable[DatasetMetadata]
) -> tuple[DatasetMetadata, ...]:
    """Return catalog datasets whose topic or ID the question explicitly names.

    Matching is intentionally lexical and conservative. The guard exists to
    stop a one-table executor from dropping a requested input; it does not try
    to infer related datasets from broad concepts.

    A question is rarely typed in the catalog's own English slugs, so a curated
    spelling is accepted too: 人口 and dân số name the population topic just as
    "population" does. The vocabulary lives in `youth_compass.ontology.topics`
    and only recognizes spellings someone wrote down there, so this stays a
    naming question rather than an inference about which tables relate.
    """

    normalized = " ".join(question.casefold().replace("_", " ").replace("-", " ").split())
    spoken_topics = set(extract_topics(question))
    matched: dict[str, DatasetMetadata] = {}
    for item in records:
        dataset_phrase = " ".join(
            item.dataset_id.casefold().replace("_", " ").replace("-", " ").split()
        )
        topic_phrase = " ".join(item.topic.casefold().replace("_", " ").split())
        if (
            _contains_phrase(normalized, dataset_phrase)
            or _contains_phrase(normalized, topic_phrase)
            or resolve_topic_name(item.topic) in spoken_topics
        ):
            matched[item.dataset_id] = item
    return tuple(matched[key] for key in sorted(matched))


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if any("\u3400" <= character <= "\u9fff" for character in phrase):
        return phrase in text
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _period_granularity(period: str) -> str:
    """Name the reporting granularity a canonical period string encodes."""

    return "month" if "-" in period else "year"


def _align_period_granularity(
    series_by_dataset: "list[tuple[DatasetMetadata, ObservationSeries]]",
) -> tuple["list[tuple[DatasetMetadata, ObservationSeries]]", tuple[str, ...]]:
    """Collapse finer series onto the coarsest granularity the inputs share.

    A monthly series becomes annual by keeping the latest month present in each
    year, which is that year's closing snapshot. This is the correct reading for
    a point-in-time count such as a population register, and the wrong reading
    for a within-year total such as births, so every collapsed input is reported
    back to the caller and stated in the answer.

    Returns the aligned series and one note per input that was changed.
    """

    granularities = {
        _period_granularity(point.period)
        for _, series in series_by_dataset
        for point in series.points
    }
    if "year" not in granularities or granularities == {"year"}:
        return series_by_dataset, ()

    aligned: list[tuple[DatasetMetadata, ObservationSeries]] = []
    notes: list[str] = []
    for metadata, series in series_by_dataset:
        monthly = [point for point in series.points if _period_granularity(point.period) == "month"]
        if not monthly:
            aligned.append((metadata, series))
            continue
        latest: dict[tuple[str, str], ObservationPoint] = {}
        for point in series.points:
            year = point.period.split("-")[0]
            key = (point.entity_id, year)
            current = latest.get(key)
            if current is None or point.period > current.period:
                latest[key] = point
        collapsed = tuple(
            point.model_copy(update={"period": key[1]})
            for key, point in sorted(latest.items(), key=lambda item: (item[0][1], item[0][0]))
        )
        aligned.append((metadata, series.model_copy(update={"points": collapsed})))
        kept = sorted({point.period for point in latest.values()})
        notes.append(
            f"{metadata.dataset_id} reports monthly and was aligned to each year's closing "
            f"month ({', '.join(kept[:6])}{', …' if len(kept) > 6 else ''}); this reads as a "
            "point-in-time count, not a within-year total"
        )
    return aligned, tuple(notes)


def _no_overlap_reason(
    series_by_dataset: "list[tuple[DatasetMetadata, ObservationSeries]]",
) -> tuple[str, str]:
    """Explain why an exact entity-period join found nothing to align.

    Returns the machine-facing reason and the reader-facing diagnosis. A
    granularity mismatch is called out by name because the fix is a policy
    decision about how to aggregate over time, not more data.
    """

    granularities = {
        metadata.dataset_id: sorted({_period_granularity(point.period) for point in series.points})
        for metadata, series in series_by_dataset
    }
    distinct = {value for values in granularities.values() for value in values}
    if len(distinct) > 1:
        described = "; ".join(
            f"{dataset_id} reports by {' and '.join(values)}"
            for dataset_id, values in granularities.items()
        )
        return (
            f"datasets report at different period granularities ({described})",
            (
                "These datasets are published at different reporting granularities, so no "
                f"period lines up exactly ({described}). Combining them would mean deciding "
                "how to aggregate one of them over time, which changes what the numbers "
                "mean, so no answer was produced."
            ),
        )
    entity_sets = {
        metadata.dataset_id: {point.entity_id for point in series.points}
        for metadata, series in series_by_dataset
    }
    if not set.intersection(*entity_sets.values()):
        return (
            "datasets cover no district in common",
            (
                "These datasets cover no district in common, so they cannot be compared "
                "without inventing an alignment."
            ),
        )
    return (
        "datasets share districts but no common reporting period",
        (
            "These datasets share districts but no common reporting period, so they cannot "
            "be compared without inventing an alignment."
        ),
    )


def _joined_observation_key(entity_id: str, period: str) -> tuple[str, str]:
    district = resolve_district_name(entity_id).district
    return (district.code if district is not None else entity_id.casefold(), period)


def _citations(
    values: tuple[FeatureValue, ...],
    question: str = "",
) -> tuple[tuple[EvidenceCitation, ...], dict[tuple[str, str, str], str]]:
    evidence_by_key = {
        (item.dataset_id, item.dataset_version, item.source_uri): item
        for value in values
        for item in value.evidence
    }
    lookup: dict[tuple[str, str, str], str] = {}
    citations: list[EvidenceCitation] = []
    language = _name_language(question)
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
                excerpt=tuple(
                    EvidenceExcerptRow(
                        entity_id=value.entity_id,
                        entity_name=readable_entity_name(value.entity_id, None, language),
                        metric_code=value.feature_code,
                        metric_name=readable_feature_name(value.feature_code, None),
                        value=value.value,
                        observed_at=value.observed_at,
                    )
                    for value in values
                    if key
                    in {
                        (evidence.dataset_id, evidence.dataset_version, evidence.source_uri)
                        for evidence in value.evidence
                    }
                )[:100],
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


def _name_language(question: str) -> NameLanguage:
    """Name places in the script the question was asked in."""

    return question_language(question)


def _candidate_insights(
    candidates: tuple[CandidateScore, ...],
    citation_lookup: dict[tuple[str, str, str], str],
    question: str = "",
) -> tuple[CandidateInsight, ...]:
    """Attach the readable label every candidate is shown under.

    The feature store keys candidates by slug, so a candidate that carries no
    published name is labelled from its identifier rather than shown as one.
    The identifier itself stays on the insight for citations and joins.
    """

    language = _name_language(question)
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
                entity_name=readable_entity_name(
                    candidate.entity_id, candidate.entity_name, language
                ),
                eligible=candidate.eligible,
                score=candidate.score,
                contributions=tuple(
                    FeatureContributionInsight(
                        feature_code=contribution.feature_code,
                        feature_name=readable_feature_name(
                            contribution.feature_code, contribution.feature_name
                        ),
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


def _decision_answer(
    *,
    question: str,
    profile_name: str,
    candidates: tuple[CandidateInsight, ...],
) -> str:
    """Explain a ranking in prose so visualizations remain supporting evidence."""

    top = candidates[0]
    top_name = top.entity_name or top.entity_id
    runner = candidates[1] if len(candidates) > 1 else None
    ranking_citations = _candidate_citations(top)
    if runner is not None:
        ranking_citations = tuple(
            dict.fromkeys((*ranking_citations, *_candidate_citations(runner)))
        )
    language = _response_language_for_fallback(question)

    if language == "zh":
        opening = f"在「{profile_name}」評分中，{top_name}以{top.score:.1f}/100排名第一"  # noqa: RUF001
        if runner is not None:
            runner_name = runner.entity_name or runner.entity_id
            opening += f"，高於第二名{runner_name}的{runner.score:.1f}/100"  # noqa: RUF001
        opening += f"。{_inline_citations(ranking_citations)}"
        reason_intro = "主要原因是"
        versus = "，相較於第二名的"  # noqa: RUF001
        points = "分貢獻"
        offset_intro = "不過，第二名在"  # noqa: RUF001
        close = "這是依目前已發布資料與既定權重得出的比較結果，並非不考慮個人需求的絕對建議。"  # noqa: RUF001
    elif language == "vi":
        opening = f"{top_name} đứng đầu cho tiêu chí {profile_name} với {top.score:.1f}/100"
        if runner is not None:
            runner_name = runner.entity_name or runner.entity_id
            opening += f", cao hơn phương án thứ hai là {runner_name} ({runner.score:.1f}/100)"
        opening += f". {_inline_citations(ranking_citations)}"
        reason_intro = "Lý do chính là"
        versus = ", so với"
        points = "điểm đóng góp"
        offset_intro = "Tuy nhiên, phương án thứ hai làm tốt hơn về"
        close = (
            "Đây là kết quả so sánh theo dữ liệu đã công bố và bộ trọng số hiện tại, "
            "không phải khuyến nghị tuyệt đối cho mọi nhu cầu cá nhân."
        )
    else:
        opening = (
            f"{top_name} ranks first for {profile_name} with a deterministic score of "
            f"{top.score:.1f}/100"
        )
        if runner is not None:
            runner_name = runner.entity_name or runner.entity_id
            opening += f", ahead of runner-up {runner_name} at {runner.score:.1f}/100"
        opening += f". {_inline_citations(ranking_citations)}"
        reason_intro = "The main reason is"
        versus = ", versus"
        points = "contribution points"
        offset_intro = "However, the runner-up performs better on"
        close = (
            "This comparison reflects the currently published data and configured weights; "
            "it is not an unconditional recommendation for every personal situation."
        )

    if runner is None:
        strongest = sorted(top.contributions, key=lambda item: item.points, reverse=True)[:2]
        reasons = "; ".join(
            f"{item.feature_name} ({item.points:.1f} {points}) {_inline_citations(item.citations)}"
            for item in strongest
        )
        return f"{opening}\n\n{reason_intro} {reasons}.\n\n{close}"

    runner_by_feature = {item.feature_code: item for item in runner.contributions}
    comparisons = [
        (
            item.points - runner_by_feature[item.feature_code].points,
            item,
            runner_by_feature[item.feature_code],
        )
        for item in top.contributions
        if item.feature_code in runner_by_feature
    ]
    advantages = sorted(
        (item for item in comparisons if item[0] > 0),
        reverse=True,
        key=lambda item: item[0],
    )
    disadvantages = sorted((item for item in comparisons if item[0] < 0), key=lambda item: item[0])

    explanation_parts = []
    for _, top_item, runner_item in advantages[:2]:
        citations = tuple(dict.fromkeys((*top_item.citations, *runner_item.citations)))
        explanation_parts.append(
            f"{top_item.feature_name}: {top_item.points:.1f} {points}{versus} "
            f"{runner_item.points:.1f} {_inline_citations(citations)}"
        )
    paragraphs = [opening]
    if explanation_parts:
        paragraphs.append(f"{reason_intro} {'; '.join(explanation_parts)}.")
    if disadvantages:
        _, top_item, runner_item = disadvantages[0]
        citations = tuple(dict.fromkeys((*top_item.citations, *runner_item.citations)))
        paragraphs.append(
            f"{offset_intro} {top_item.feature_name}: {runner_item.points:.1f} {points}{versus} "
            f"{top_item.points:.1f} {_inline_citations(citations)}."
        )
    paragraphs.append(close)
    return "\n\n".join(paragraphs)


def _candidate_citations(candidate: CandidateInsight) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            citation
            for contribution in candidate.contributions
            for citation in contribution.citations
        )
    )


def _inline_citations(citation_ids: tuple[str, ...]) -> str:
    return " ".join(f"[{citation_id}]" for citation_id in citation_ids)


def _response_language_for_fallback(question: str) -> str:
    language = question_language(question)
    if language is NameLanguage.ZH_HANT:
        return "zh"
    return "vi" if language is NameLanguage.VIETNAMESE else "en"


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

    language = _name_language(question)
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

    language = _response_language_for_fallback(question)
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
        name = readable_entity_name(change.entity_id, change.entity_name, _name_language(question))
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
        name = readable_entity_name(change.entity_id, change.entity_name, _name_language(question))
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


def _population_shock(question: str) -> int | None:
    """Extract a bounded, explicitly stated people count from a scenario question."""

    match = re.search(
        r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{1,7})\s*"
        # Chinese counts the noun through a measure word: 2,000 名青年.
        r"(?:名|位|個)?\s*"
        r"(?:thanh\s+niên|người|young\s+people|youth|people|persons|residents|青年|人)",
        question.casefold(),
    )
    if match is None:
        return None
    amount = int(match.group(1).replace(".", "").replace(",", ""))
    if amount <= 0 or amount > 1_000_000:
        return None
    departure = any(
        term in question.casefold()
        for term in ("rời", "chuyển đi", "leave", "depart", "搬出", "離開")
    )
    return -amount if departure else amount


def _scenario_target_year(question: str) -> int | None:
    years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)]
    plausible = [year for year in years if 2026 <= year <= 2043]
    return max(plausible) if plausible else None


def _impact_data_gaps(question: str) -> tuple[ImpactDataGap, ...]:
    """Declare the exact evidence needed for each requested downstream link."""

    normalized = question.casefold()
    generic = any(
        term in normalized
        for term in ("hạ tầng", "infrastructure", "đầu tư", "invest", "投資", "基礎設施")
    )
    gaps: list[ImpactDataGap] = []
    if generic or any(
        term in normalized
        for term in ("giá nhà", "nhà ở", "housing", "house price", "property", "住宅", "房價")
    ):
        gaps.append(
            ImpactDataGap(
                domain="housing",
                required_metrics=(
                    "housing_unit_stock",
                    "vacant_housing_units",
                    "residential_completions",
                    "youth_household_size",
                ),
                reason=(
                    "Housing demand and price pressure require district supply, vacancy, "
                    "completion, and household-formation evidence."
                ),
            )
        )
    if generic or any(
        term in normalized
        for term in ("giao thông", "transit", "transport", "metro", "bus", "交通", "捷運", "公車")
    ):
        gaps.append(
            ImpactDataGap(
                domain="transport",
                required_metrics=(
                    "transit_stop_coverage",
                    "transit_boardings",
                    "service_frequency",
                    "passenger_capacity",
                    "youth_mode_share",
                ),
                reason=(
                    "Transport pressure requires observed demand, service frequency, usable "
                    "capacity, and a youth travel-mode share."
                ),
            )
        )
    if generic or any(
        term in normalized
        for term in ("dịch vụ", "service", "y tế", "childcare", "醫療", "公共服務")
    ):
        gaps.append(
            ImpactDataGap(
                domain="public_services",
                required_metrics=(
                    "service_facility_count",
                    "service_facility_capacity",
                    "service_utilization",
                    "youth_service_usage_rate",
                ),
                reason=(
                    "A service recommendation requires facility capacity, current utilization, "
                    "and an age-compatible usage rate."
                ),
            )
        )
    return tuple(gaps)


def _impact_gap_answer(impact: ImpactAnalysis, candidates_found: bool, question: str) -> str:
    finding = impact.findings[0]
    gap_names = ", ".join(gap.domain.replace("_", " ") for gap in impact.data_gaps)
    if _response_language_for_fallback(question) == "vi":
        discovery = (
            "Agent đã tìm thấy nguồn chính thức có thể đưa vào quy trình kiểm duyệt."
            if candidates_found
            else (
                "Agent đã tìm trong catalog và danh sách nguồn được phép nhưng chưa có "
                "nguồn phù hợp."
            )
        )
        return (
            f"Đến {impact.target_year}, baseline của {impact.district_name} là "
            f"{finding.baseline_value:,.0f} người 18-35 tuổi. Với giả định "
            f"{impact.shock_people:+,} người, scenario là {finding.scenario_value:,.0f}.\n\n"
            f"Chưa thể khuyến nghị đầu tư cho {gap_names}: dữ liệu sức chứa và mức sử dụng "
            f"chưa đủ để ước tính chuỗi tác động. {discovery}"
        )
    discovery = (
        "The agent found allowlisted official sources that can enter review."
        if candidates_found
        else (
            "The agent searched the catalog and allowlisted sources but found no compatible source."
        )
    )
    return (
        f"By {impact.target_year}, the {impact.district_name} baseline is "
        f"{finding.baseline_value:,.0f} residents aged 18-35. With the "
        f"{impact.shock_people:+,} person assumption, the scenario is "
        f"{finding.scenario_value:,.0f}.\n\n"
        f"I cannot yet recommend investment in {gap_names}: capacity and utilization evidence "
        f"is incomplete. {discovery}"
    )


def _impact_population_answer(impact: ImpactAnalysis, question: str) -> str:
    finding = impact.findings[0]
    if _response_language_for_fallback(question) == "vi":
        return (
            f"Đến {impact.target_year}, {impact.district_name} có baseline "
            f"{finding.baseline_value:,.0f} người 18-35 tuổi và scenario "
            f"{finding.scenario_value:,.0f}, chênh {finding.absolute_delta:+,.0f} người."
        )
    return (
        f"By {impact.target_year}, {impact.district_name} has a baseline of "
        f"{finding.baseline_value:,.0f} residents aged 18-35 and a scenario of "
        f"{finding.scenario_value:,.0f}, a difference of {finding.absolute_delta:+,.0f}."
    )


_IMPACT_CHART_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "year": "Year",
        "residents": "Residents aged 18-35",
        "difference": "Scenario minus baseline",
        "trajectory_title": "Youth population impact through {year}",
        "trajectory_description": (
            "Observed cohorts under the baseline and user-supplied population shock."
        ),
        "difference_title": "Gap between the scenario and the baseline through {year}",
        "difference_description": (
            "Scenario minus baseline for each year. The two absolute paths sit within a "
            "few thousand people of each other, so the gap is plotted on its own axis "
            "instead of being left invisible on a shared one."
        ),
    },
    "zh": {
        "year": "年份",
        "residents": "18-35 歲居民",
        "difference": "情境減基線",
        "trajectory_title": "青年人口影響（至 {year} 年）",  # noqa: RUF001
        "trajectory_description": "在基線與使用者設定的人口變動下，觀測世代的推估結果。",  # noqa: RUF001
        "difference_title": "情境與基線的差距（至 {year} 年）",  # noqa: RUF001
        "difference_description": (
            "每一年的情境值減去基線值。兩條絕對數線相差僅數千人，"  # noqa: RUF001
            "放在同一座標軸上看不出差異，因此差距另外以自己的軸呈現。"  # noqa: RUF001
        ),
    },
    "vi": {
        "year": "Năm",
        "residents": "Cư dân 18-35 tuổi",
        "difference": "Kịch bản trừ baseline",
        "trajectory_title": "Tác động dân số thanh niên đến {year}",
        "trajectory_description": (
            "Các thế hệ quan sát được theo baseline và mức thay đổi dân số do người dùng đặt."
        ),
        "difference_title": "Chênh lệch giữa kịch bản và baseline đến {year}",
        "difference_description": (
            "Kịch bản trừ baseline theo từng năm. Hai đường tuyệt đối chỉ cách nhau vài "
            "nghìn người nên chênh lệch được vẽ trên trục riêng thay vì biến mất trên "
            "trục chung."
        ),
    },
}


def _impact_visualizations(
    scenario: YouthPopulationScenarioResult, question: str
) -> tuple[VisualizationSpec, ...]:
    """Chart the gap first, then the two absolute paths.

    A shock of a few thousand people against a city total near a million is
    about a quarter of one percent: on a shared axis the baseline and scenario
    lines are one stroke, which reads as "nothing changed". The difference
    series carries the same grounded numbers on an axis where it is legible;
    the absolute trajectory stays so the level is not lost.
    """

    labels = _IMPACT_CHART_LABELS[_response_language_for_fallback(question)]
    difference_rows: tuple[dict[str, str | int | float | bool | None], ...] = tuple(
        {"year": point.year, "difference": point.absolute_delta} for point in scenario.trajectory
    )
    trajectory_rows: tuple[dict[str, str | int | float | bool | None], ...] = tuple(
        {
            "year": point.year,
            "path": path,
            "population": value,
        }
        for point in scenario.trajectory
        for path, value in (
            ("Baseline", point.baseline_value),
            ("Scenario", point.scenario_value),
        )
    )
    difference = VisualizationSpec(
        visualization_id="impact-population-difference",
        type=VisualizationType.COMPARISON_BAR,
        title=labels["difference_title"].format(year=scenario.target_year),
        description=labels["difference_description"],
        x=VisualizationEncoding(
            field="year", label=labels["year"], data_type="temporal", unit=None
        ),
        y=VisualizationEncoding(
            field="difference",
            label=labels["difference"],
            data_type="quantitative",
            unit="persons",
        ),
        rows=difference_rows,
    )
    trajectory = VisualizationSpec(
        visualization_id="impact-population-trajectory",
        type=VisualizationType.LINE,
        title=labels["trajectory_title"].format(year=scenario.target_year),
        description=labels["trajectory_description"],
        x=VisualizationEncoding(
            field="year", label=labels["year"], data_type="temporal", unit=None
        ),
        y=VisualizationEncoding(
            field="population",
            label=labels["residents"],
            data_type="quantitative",
            unit="persons",
        ),
        series_field="path",
        rows=trajectory_rows,
    )
    return (difference, trajectory)


def _grounded_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
