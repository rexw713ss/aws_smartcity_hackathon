"""Deterministic, evidence-grounded copilot orchestration.

This module is the orchestrator and nothing else: it resolves follow-up context,
routes one decomposed question to the pipeline that can answer it, and records
the routing decisions in the trace. Every pipeline lives beside it and owns its
own retrieval and prose:

- `youth_compass.agent.decision_answering` — profile-weighted candidate ranking
- `youth_compass.agent.observation_answering` — catalog, observations, forecasts
- `youth_compass.agent.multi_dataset` — exact joins across several tables
- `youth_compass.agent.impact` — bounded population scenarios
- `youth_compass.agent.support` — the response envelope they share
"""

import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime

from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent.answering import (
    AnswerComposer,
    DeterministicAnswerComposer,
    FallbackAnswerComposer,
)
from youth_compass.agent.contracts import (
    AnalysisOperation,
    AnswerCompositionContext,
    ConversationContext,
    CopilotResponse,
    CopilotStatus,
    DecomposedQuery,
    Decomposition,
    DecompositionSource,
    RoutedToolPlan,
    ToolCapability,
    ToolTrace,
    WebCitation,
)
from youth_compass.agent.conversation import (
    ConversationContextResolver,
    ConversationContextStore,
    context_from_decomposition,
    new_session_id,
)
from youth_compass.agent.decision_answering import DecisionAnswering
from youth_compass.agent.grounding import quarantine
from youth_compass.agent.impact import answer_impact_scenario
from youth_compass.agent.limitations import DataLimitationsBuilder
from youth_compass.agent.observation_answering import ObservationAnswering
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
    register_web_search_capabilities,
)
from youth_compass.agent.support import AnswerSupport, grounded_json
from youth_compass.agent.visualization import VisualizationBuilder
from youth_compass.decisioning import (
    DecisionProfileRegistry,
    FeatureProvider,
    FeatureRegistry,
    YouthPopulationScenarioService,
)
from youth_compass.domain.errors import (
    WebSearchError,
    YouthCompassError,
)
from youth_compass.ontology import (
    NameLanguage,
    extract_districts,
    question_language,
)
from youth_compass.ports import (
    ForecastService,
    WebSearchProvider,
    WebSearchRequest,
)

_LOGGER = logging.getLogger(__name__)


class GroundedCopilotService:
    """Plan, retrieve, rank, and explain without delegating facts to an LLM."""

    def __init__(
        self,
        *,
        feature_provider: FeatureProvider,
        feature_registry: FeatureRegistry,
        profile_registry: DecisionProfileRegistry,
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
        web_search: WebSearchProvider | None = None,
        web_search_result_limit: int = 5,
        web_search_country: str | None = "TW",
    ) -> None:
        if not 1 <= web_search_result_limit <= 10:
            raise ValueError("web_search_result_limit must be between 1 and 10")
        self._decomposer = decomposer or DeterministicQueryDecomposer()
        self._profiles = profile_registry
        self._conversation_store = conversation_store
        self._conversation_resolver = conversation_resolver or ConversationContextResolver()
        self._scenario_service = scenario_service
        self._web_search = web_search
        self._web_search_result_limit = web_search_result_limit
        self._web_search_country = web_search_country
        deterministic_composer = DeterministicAnswerComposer()
        self._answer_composer: AnswerComposer = (
            FallbackAnswerComposer(answer_composer, deterministic_composer)
            if answer_composer is not None
            else deterministic_composer
        )
        self._support = AnswerSupport(
            visualizations=visualization_builder or VisualizationBuilder(),
            limitations=DataLimitationsBuilder(),
            composer=self._answer_composer,
            acquisition=acquisition,
        )
        self._decisions = DecisionAnswering(
            feature_provider=feature_provider,
            feature_registry=feature_registry,
            profile_registry=profile_registry,
            support=self._support,
        )
        self._observations = (
            ObservationAnswering(
                tools=observation_tools,
                support=self._support,
                forecast_service=forecast_service,
            )
            if observation_tools is not None
            else None
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
        if capabilities is None and web_search is not None:
            register_web_search_capabilities(self._capabilities)
        self._router = SmartToolRouter(self._capabilities)

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
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        """Resolve structured follow-up context, then execute one grounded turn."""

        now = datetime.now(UTC)
        requested_entities = tuple(dict.fromkeys(entity_ids))
        active_session_id = session_id
        previous = None
        if self._conversation_store is not None:
            active_session_id = active_session_id or new_session_id()
            previous = self._read_context(active_session_id)
        planned = await self._decomposer.decompose(question, requested_entities)
        # Scope from the question before session scope is applied: a district
        # the person just named must win over the one carried by the session.
        initial, question_scope = _scope_from_question(question, planned.query)
        decomposition, context_applied = self._conversation_resolver.resolve(
            question, initial, previous
        )
        response = await self._execute(
            question,
            now=now,
            min_quality_score=min_quality_score,
            decomposition=decomposition,
            provenance=planned,
            context_applied=context_applied,
            question_scope=question_scope,
            on_text=on_text,
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

        store = self._conversation_store
        if store is None:  # Defensive: callers enter only when a store is configured.
            raise RuntimeError("conversation store is unavailable")
        try:
            return store.get(session_id)
        except YouthCompassError as exc:
            _LOGGER.warning("conversation context unavailable for this turn: %s", exc)
            return None

    def _write_context(self, context: ConversationContext) -> None:
        """Persist session scope, never failing the answer already produced."""

        store = self._conversation_store
        if store is None:  # Defensive: callers enter only when a store is configured.
            raise RuntimeError("conversation store is unavailable")
        try:
            store.put(context)
        except YouthCompassError as exc:
            _LOGGER.warning("conversation context was not persisted: %s", exc)

    async def _execute(
        self,
        question: str,
        *,
        now: datetime,
        min_quality_score: float,
        decomposition: DecomposedQuery,
        provenance: Decomposition | None = None,
        context_applied: bool,
        question_scope: tuple[str, ...] = (),
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        """Execute one already-resolved decomposition without reading session state."""

        routed_plan = self._router.route(decomposition)
        source = (
            provenance.source.value if provenance is not None else DecompositionSource.MODEL.value
        )
        trace = [
            ToolTrace(
                tool="query_decomposer",
                outcome="clarification" if decomposition.needs_clarification else "decomposed",
                summary=(
                    f"planned by {source} — {decomposition.objective}: "
                    f"{', '.join(item.value for item in decomposition.operations)}"
                ),
            )
        ]
        # A plan produced by the fallback is a different plan, so the reason the
        # primary decomposer was skipped belongs in the audit trail beside it.
        if provenance is not None and provenance.degraded_reason is not None:
            trace.append(
                ToolTrace(
                    tool="query_decomposer",
                    outcome="degraded",
                    summary=(
                        "the primary decomposer was unavailable and the keyword table "
                        f"planned this turn instead: {provenance.degraded_reason}"
                    ),
                )
            )
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
        # One decomposition, one dispatch. Everything below reads the same
        # classification: the two refusals that apply to every shape of question
        # come first, then the operations select which pipeline runs.
        if decomposition.needs_clarification:
            return CopilotResponse(
                status=CopilotStatus.UNSUPPORTED_QUESTION,
                answer=decomposition.clarification_question or "Please clarify the analysis goal.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No data tool was executed before clarification.",),
            )
        if not routed_plan.executable:
            missing = ", ".join(item.value for item in routed_plan.missing_operations)
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=(
                    "I understood the requested analysis, but this runtime is missing the "
                    f"following validated capabilities: {missing}."
                ),
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("The router failed closed; no partial conclusion was produced.",),
            )
        operations = decomposition.operations
        if AnalysisOperation.SEARCH_WEB in operations and self._web_search is not None:
            return await self._answer_web_search(
                now, decomposition, routed_plan, trace, on_text=on_text
            )
        if AnalysisOperation.SIMULATE_SCENARIO in operations:
            return answer_impact_scenario(
                now,
                decomposition,
                routed_plan,
                trace,
                scenarios=self._scenario_service,
                support=self._support,
            )
        if AnalysisOperation.RANK_CANDIDATES in operations:
            return await self._answer_decision(
                now, decomposition, routed_plan, trace, min_quality_score, on_text
            )
        if self._observations is not None and AnalysisOperation.INSPECT_DATASET in operations:
            return await self._observations.answer(
                now,
                decomposition,
                routed_plan,
                trace,
                min_quality_score=min_quality_score,
                on_text=on_text,
            )
        return CopilotResponse(
            status=CopilotStatus.UNSUPPORTED_QUESTION,
            answer="No registered analysis can safely execute this question.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=("No data query or ranking was executed.",),
        )

    async def _answer_decision(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        min_quality_score: float,
        on_text: Callable[[str], Awaitable[None]] | None,
    ) -> CopilotResponse:
        """Rank a registered profile, refusing when the named one is not registered.

        The decomposer proposes a profile name; only the registry knows which
        names exist in this runtime. Checking here is what keeps a plausible
        invention from reaching the scoring engine, and it is also the honest
        answer to a real decision question the deployment cannot serve.
        """

        profile_code = decomposition.decision_profile
        registered = {item.profile_code for item in self._profiles.list()}
        if profile_code is None or profile_code not in registered:
            trace.append(
                ToolTrace(
                    tool="resolve_decision_profile",
                    outcome="unsupported",
                    summary=(
                        f"no registered profile named {profile_code!r}; "
                        f"registered: {', '.join(sorted(registered)) or 'none'}"
                    ),
                )
            )
            return CopilotResponse(
                status=CopilotStatus.UNSUPPORTED_QUESTION,
                answer="No registered decision profile can safely execute this question.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No data query or ranking was executed.",),
            )
        trace.append(
            ToolTrace(
                tool="resolve_decision_profile",
                outcome="ok",
                summary=f"matched the question to registered profile {profile_code}",
            )
        )
        return await self._decisions.rank(
            decomposition.original_question,
            now=now,
            profile_code=profile_code,
            decomposition=decomposition,
            routed_plan=routed_plan,
            trace=trace,
            min_quality_score=min_quality_score,
            on_text=on_text,
        )

    async def _answer_web_search(
        self,
        now: datetime,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        *,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        """Search current web results and keep them separate from curated evidence."""

        assert self._web_search is not None
        search_lang = _web_search_language(decomposition.original_question)
        try:
            results = await self._web_search.search(
                WebSearchRequest(
                    query=decomposition.original_question,
                    count=self._web_search_result_limit,
                    country=self._web_search_country,
                    search_lang=search_lang,
                )
            )
        except WebSearchError as exc:
            trace.append(ToolTrace(tool="web_search", outcome="failed", summary=str(exc)[:300]))
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer="Web search is temporarily unavailable.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No web claim was produced because the search provider failed.",),
            )
        citations = tuple(
            WebCitation(
                citation_id=f"web-{index}",
                title=result.title,
                url=result.url,
                snippet=result.description,
                published_at=result.published_at,
            )
            for index, result in enumerate(results, start=1)
        )
        trace.append(
            ToolTrace(
                tool="web_search",
                outcome="ok" if citations else "no_match",
                summary=f"returned {len(citations)} validated HTTPS results",
            )
        )
        if not citations:
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer="The web search returned no results for this question.",
                generated_at=now,
                decomposition=decomposition,
                routed_plan=routed_plan,
                tool_trace=tuple(trace),
                warnings=("No web claim was produced without a source.",),
            )
        fallback_answer = "\n".join(
            ["I found these current web results:"]
            + [
                f"- {item.title} — {item.snippet or 'Open the source for details.'} "
                f"[{item.citation_id}]"
                for item in citations
            ]
        )
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=decomposition.original_question,
                analysis_type="web_search",
                # Titles and snippets are written by whoever owns the page. This
                # is the most plainly attacker-controlled text in the system, so
                # it is quarantined the same way catalog text is.
                grounded_facts_json=grounded_json(
                    {
                        "results": [
                            {
                                "citation_id": item.citation_id,
                                "title": quarantine(item.title),
                                "snippet": quarantine(item.snippet),
                                "published_at": (
                                    item.published_at.isoformat() if item.published_at else None
                                ),
                            }
                            for item in citations
                        ]
                    }
                ),
                allowed_citation_ids=tuple(item.citation_id for item in citations),
                fallback_answer=fallback_answer,
            ),
            trace,
            on_text=on_text,
        )
        return CopilotResponse(
            status=CopilotStatus.ANSWERED,
            answer=answer,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            web_citations=citations,
            tool_trace=tuple(trace),
            assumptions=(
                "Web snippets are search-provider excerpts, not curated New Taipei Youth Policy datasets.",
            ),
        )


def _web_search_language(question: str) -> str:
    """Return the Brave language token, preserving Vietnamese search intent."""

    normalized = question.casefold()
    if any(
        cue in normalized
        for cue in ("tìm", "kiếm", "tra cứu", "tin mới", "tin tức", "chính sách", "thanh niên")
    ):
        return "vi"
    if question_language(question) is NameLanguage.ZH_HANT:
        return "zh-hant"
    return "en"


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
