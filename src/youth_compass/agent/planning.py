"""Query decomposition, capability discovery, and deterministic tool routing."""

import json
import logging
import re
from typing import Protocol

from pydantic import ValidationError

from youth_compass.agent.contracts import (
    AnalysisOperation,
    DecomposedQuery,
    Decomposition,
    DecompositionSource,
    QuestionFocus,
    RoutedToolPlan,
    RoutedToolStep,
    ToolCapability,
)
from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ontology import extract_topics
from youth_compass.ports import ModelProvider, ModelRequest


class QueryDecomposer(Protocol):
    """Turn a question into generic, schema-validated analysis operations."""

    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> Decomposition:
        """Return a decomposition and its provenance, executing no tool."""
        ...


_LOGGER = logging.getLogger(__name__)


class DeterministicQueryDecomposer:
    """The keyword-table fallback: recognizes question shapes someone wrote down.

    This is the safety net behind ``ModelQueryDecomposer``, not the primary path.
    It matches curated cues in English, Vietnamese, and Traditional Chinese, so
    it answers the shapes it was taught and asks for clarification on everything
    else. That property is exactly why it cannot be the main route: adding a new
    question shape means adding cues in three languages, and it is most brittle
    at the point where phrasing varies most.

    It stays because a decomposer that fails takes the whole turn with it. When
    the model provider is unavailable, matching keywords is a better answer than
    an error, and the ``Decomposition.source`` it reports makes the downgrade
    visible instead of silent.
    """

    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> Decomposition:
        return Decomposition(
            query=self._decompose(question, entity_ids),
            source=DecompositionSource.KEYWORD_TABLE,
        )

    def _decompose(self, question: str, entity_ids: tuple[str, ...]) -> DecomposedQuery:
        normalized = " ".join(question.casefold().split())
        decision_profile = _decision_profile(normalized)
        decision = decision_profile is not None
        compare = _contains(
            normalized, "compare", "so sánh", "khác nhau", "versus", " vs ", "比較", "相比"
        )
        trend = _contains(
            normalized,
            "trend",
            "xu hướng",
            "tăng",
            "giảm",
            "over time",
            "趨勢",
            "變化",
            "成長",
            "下降",
        )
        forecast = _contains(
            normalized, "forecast", "dự báo", "predict", "tương lai", "預測", "預估", "未來"
        )
        overview = _contains(
            normalized,
            "overview",
            "tổng quan",
            "概覽",
            "總覽",
        )
        # An overview of a named topic asks for the observations themselves.
        # Keep it separate from catalog discovery: the UI appends
        # ``Dataset topic: ...`` as scope metadata, and treating that internal
        # word as user intent used to turn every overview suggestion into a
        # list of all published datasets.
        topic_overview = overview and bool(extract_topics(question))
        discover = _contains(
            normalized,
            "dataset",
            "data source",
            "nguồn dữ liệu",
            "dữ liệu nào",
            "what data",
            "資料集",
            "資料來源",
            "有哪些資料",
        )
        scenario = _contains(
            normalized,
            "what if",
            "nếu",
            "giả sử",
            "thêm người",
            "chuyển đến",
            "move to",
            "moves to",
            "搬入",
            "如果",
        ) and bool(re.search(r"\d", normalized))
        web = _contains(
            normalized,
            "search the web",
            "web search",
            "search online",
            "look up online",
            "google",
            "tìm trên web",
            "tìm kiếm web",
            "tra cứu web",
            "tin mới",
            "tin tức mới",
            "網路搜尋",
            "搜尋網路",
            "最新消息",
        )

        operations: list[AnalysisOperation] = [AnalysisOperation.SEARCH_CATALOG]
        objective = "discover relevant evidence"
        needs_clarification = False
        clarification_question = None
        focus = None if scenario or decision else _question_focus(normalized, forecast=forecast)
        if web:
            objective = "search the public web for current information"
            operations = [AnalysisOperation.SEARCH_WEB]
            focus = None
        elif focus is not None:
            objective, focus_operations = _FOCUS_PLANS[focus]
            operations.extend(focus_operations)
        elif scenario:
            objective = "simulate a population shock and assess infrastructure capacity"
            operations = [AnalysisOperation.SEARCH_TOOLS, AnalysisOperation.SEARCH_CATALOG]
            operations.extend(
                (
                    AnalysisOperation.SIMULATE_SCENARIO,
                    AnalysisOperation.ASSESS_CAPACITY,
                    AnalysisOperation.DISCOVER_SOURCES,
                    AnalysisOperation.RECOMMEND_INVESTMENT,
                    AnalysisOperation.EXPLAIN_LINEAGE,
                )
            )
        elif decision:
            objective = "rank candidates for a location decision"
            operations.extend(
                (
                    AnalysisOperation.GET_FEATURES,
                    AnalysisOperation.RANK_CANDIDATES,
                    AnalysisOperation.EXPLAIN_LINEAGE,
                )
            )
        elif forecast:
            objective = "forecast a metric"
            operations.extend(
                (
                    AnalysisOperation.INSPECT_DATASET,
                    AnalysisOperation.FORECAST_METRIC,
                    AnalysisOperation.EXPLAIN_LINEAGE,
                )
            )
        elif trend or compare or topic_overview:
            objective = (
                "compare observations"
                if compare
                else "analyze a time trend"
                if trend
                else "summarize published observations"
            )
            operations.extend(
                (AnalysisOperation.INSPECT_DATASET, AnalysisOperation.QUERY_OBSERVATIONS)
            )
            if len(_metric_terms(normalized)) > 1:
                operations.append(AnalysisOperation.JOIN_OBSERVATIONS)
            # A topic overview must also work for a newly published dataset
            # that has only one period. The series profiler and visualization
            # builder can still summarize that snapshot without manufacturing
            # a first-to-last comparison.
            if trend or compare:
                operations.append(AnalysisOperation.COMPARE_ENTITIES)
            operations.append(AnalysisOperation.EXPLAIN_LINEAGE)
        elif discover:
            operations.append(AnalysisOperation.INSPECT_DATASET)
        else:
            needs_clarification = True
            clarification_question = (
                "What metric, geography, time period, or decision should be analyzed?"
            )
        return DecomposedQuery(
            original_question=question,
            objective=objective,
            subject_terms=_subject_terms(normalized),
            metric_terms=_metric_terms(normalized),
            entity_ids=entity_ids,
            time_expression=_time_expression(normalized),
            operations=tuple(operations),
            focus=focus,
            # Only a plan that actually ranks candidates carries a profile. A web
            # or scenario question can mention a home without asking for one.
            decision_profile=(
                decision_profile if AnalysisOperation.RANK_CANDIDATES in operations else None
            ),
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
        )


# The decision profiles the keyword table can recognize, and the cues that name
# them. Ordered, so a question naming both subjects resolves to the first listed
# rather than to whichever dict iteration happened to reach first.
_PROFILE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "home_buying",
        (
            "mua nhà",
            "nha o dau",
            "nhà ở đâu",
            "home buying",
            "buy a home",
            "buy house",
            "housing location",
            "買房",
            "購屋",
        ),
    ),
    (
        "ev_charger_placement",
        (
            "trụ sạc",
            "trạm sạc",
            "tru sac",
            "tram sac",
            "ev charger",
            "charging station",
            "charger placement",
            "充電站",
            "充電樁",
        ),
    ),
)


def _decision_profile(normalized: str) -> str | None:
    """Name the registered decision profile a question asks to run, or None."""

    for profile_code, cues in _PROFILE_CUES:
        if _contains(normalized, *cues):
            return profile_code
    return None


#: Profile codes a decomposer may propose. Whether one is registered in a given
#: runtime is the profile registry's call, not the decomposer's.
KNOWN_DECISION_PROFILES: tuple[str, ...] = tuple(code for code, _ in _PROFILE_CUES)


_OBSERVATION_AUDIT = (
    AnalysisOperation.INSPECT_DATASET,
    AnalysisOperation.QUERY_OBSERVATIONS,
    AnalysisOperation.EXPLAIN_LINEAGE,
)
_RANKED_CHANGE = (
    AnalysisOperation.INSPECT_DATASET,
    AnalysisOperation.QUERY_OBSERVATIONS,
    AnalysisOperation.COMPARE_ENTITIES,
    AnalysisOperation.EXPLAIN_LINEAGE,
)
_CATALOG_AUDIT = (AnalysisOperation.INSPECT_DATASET, AnalysisOperation.EXPLAIN_LINEAGE)

# The objective and tools each focused data question needs. Every step here is
# an existing registered capability, so the router validates these plans the
# same way it validates any other.
_FOCUS_PLANS: dict[QuestionFocus, tuple[str, tuple[AnalysisOperation, ...]]] = {
    QuestionFocus.LARGEST_DECLINE: (
        "rank districts by share of youth population lost",
        _RANKED_CHANGE,
    ),
    QuestionFocus.PRIORITY_EXPLANATION: ("explain a district's decline ranking", _RANKED_CHANGE),
    QuestionFocus.COMPLETENESS: (
        "check reporting completeness of the latest period",
        _OBSERVATION_AUDIT,
    ),
    QuestionFocus.ESTIMATES: ("identify estimated rather than reported values", _OBSERVATION_AUDIT),
    QuestionFocus.EVIDENCE_SUMMARY: (
        "summarize published evidence for districts",
        _OBSERVATION_AUDIT,
    ),
    QuestionFocus.POPULATION_SCOPE: ("state which population a dataset counts", _CATALOG_AUDIT),
    QuestionFocus.VERSION_CHANGES: ("describe what a new dataset version changed", _CATALOG_AUDIT),
    QuestionFocus.JOINABILITY: ("assess whether two datasets join directly", _CATALOG_AUDIT),
    QuestionFocus.FORECAST_ACCURACY: (
        "report forecast backtest accuracy",
        (
            AnalysisOperation.INSPECT_DATASET,
            AnalysisOperation.FORECAST_METRIC,
            AnalysisOperation.EXPLAIN_LINEAGE,
        ),
    ),
}

# Ordered: the first matching focus wins, so a more specific question shape is
# listed before a broader one that shares its words.
_FOCUS_CUES: tuple[tuple[QuestionFocus, tuple[str, ...]], ...] = (
    (
        QuestionFocus.JOINABILITY,
        (
            "joined directly",
            "be joined",
            "join directly",
            "joinable",
            "ghép trực tiếp",
            "kết hợp trực tiếp",
            "直接合併",
            "直接串接",
            "能否合併",
            "可以合併",
        ),
    ),
    (
        QuestionFocus.VERSION_CHANGES,
        (
            "what changed",
            "changed after",
            "changes after",
            "since the new",
            "thay đổi gì",
            "có gì thay đổi",
            "改變了什麼",
            "有何改變",
            "新版本",
        ),
    ),
    (
        QuestionFocus.EVIDENCE_SUMMARY,
        (
            "evidence summary",
            "one-page",
            "one page summary",
            "tóm tắt bằng chứng",
            "bản tóm tắt",
            "證據摘要",
            "一頁摘要",
        ),
    ),
    (
        QuestionFocus.PRIORITY_EXPLANATION,
        (
            "high priority",
            "marked priority",
            "priority district",
            "ưu tiên cao",
            "được ưu tiên",
            "高優先",
            "列為優先",
        ),
    ),
    (
        QuestionFocus.LARGEST_DECLINE,
        (
            "lost the largest",
            "largest share",
            "largest decline",
            "biggest decline",
            "declined the most",
            "fell the most",
            "lost the most",
            "giảm nhiều nhất",
            "mất nhiều nhất",
            "減少最多",
            "下降最多",
            "流失最多",
        ),
    ),
    (
        QuestionFocus.ESTIMATES,
        ("estimates", "estimated value", "exact counts", "ước tính", "ước lượng", "估計值", "估算"),
    ),
    (
        QuestionFocus.COMPLETENESS,
        ("complete", "completeness", "đầy đủ", "完整"),
    ),
)
_ACCURACY_CUES = (
    "accurate",
    "accuracy",
    "backtest",
    "forecast error",
    "độ chính xác",
    "sai số",
    "準確",
    "誤差",
)
_SCOPE_CUES = (
    "income of youth",
    "of youth residents",
    "youth-specific",
    "specific to youth",
    "của thanh niên",
    "riêng thanh niên",
    "青年的",
    "青年專屬",
)


def _question_focus(normalized: str, *, forecast: bool) -> QuestionFocus | None:
    """Recognize a focused data question from curated cues, or return None."""

    if forecast and _contains(normalized, *_ACCURACY_CUES):
        return QuestionFocus.FORECAST_ACCURACY
    if _contains(normalized, *_SCOPE_CUES):
        return QuestionFocus.POPULATION_SCOPE
    for focus, cues in _FOCUS_CUES:
        if _contains(normalized, *cues):
            return focus
    return None


class ModelQueryDecomposer:
    """Schema-constrained decomposer for a Bedrock-backed ModelProvider."""

    def __init__(
        self,
        provider: ModelProvider,
        capabilities: "ToolCapabilityRegistry | None" = None,
        *,
        allowed_profiles: tuple[str, ...] = KNOWN_DECISION_PROFILES,
    ) -> None:
        self._provider = provider
        # The operation glossary is read from the registry the router will search,
        # so the prompt cannot drift from the tools that actually exist. Without
        # it the model guesses project-specific semantics — picking
        # discover_sources (external sources) over search_catalog (already
        # published), or omitting explain_lineage entirely.
        self._capabilities = capabilities
        self._allowed_profiles = frozenset(allowed_profiles)

    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> Decomposition:
        response = await self._provider.generate(
            ModelRequest(
                system=(
                    "Decompose the question into safe analysis operations. Return only JSON "
                    "matching the schema. Do not name tools, SQL, tables, or storage paths.\n"
                    "`operations` must be drawn only from this list, in execution order:\n"
                    + self._operation_glossary()
                    + "\n"
                    "Keep every string field short: `objective` is one clause, "
                    "`subject_terms` and `metric_terms` are single words or short noun "
                    "phrases. Never write an explanatory sentence into a field, and never "
                    "explain your reasoning inside a value.\n"
                    "`time_expression` is the bare period the user named, at most a few "
                    "words (for example '2023 to 2025' or 'past 5 years'). If the question "
                    "names no concrete period — 'future', 'recently', or nothing at all — "
                    "set it to null. Do not describe why it is unknown.\n"
                    "Start with search_catalog for anything the published catalog may "
                    "already hold; discover_sources is only for data the catalog lacks. "
                    "Treat a line beginning `Dataset topic:` as scope metadata, never as a "
                    "request to list datasets. An overview of a named or selected topic is an "
                    "observation request: use search_catalog, inspect_dataset, "
                    "query_observations, and explain_lineage. Add compare_entities only when "
                    "the user explicitly asks for a trend or comparison. Reserve a catalog-only "
                    "answer for an explicit inventory question such as which datasets or data "
                    "sources are available. "
                    "For a multi-step what-if question, start with search_tools, then use "
                    "simulate_scenario and assess_capacity before discover_sources or "
                    "recommend_investment. "
                    "End with explain_lineage whenever the answer will cite evidence.\n"
                    "Set `decision_profile` only when the question asks where to site or "
                    "choose something and rank_candidates is in `operations`. It must be "
                    "exactly one of: "
                    + (", ".join(sorted(self._allowed_profiles)) or "(none registered)")
                    + ". Never invent a profile name; leave it null when none applies.\n"
                    "Set `needs_clarification` only when the question names no analysable "
                    "subject at all. A question that names a subject and a period is "
                    "answerable: decompose it and let the downstream tools report whatever "
                    "evidence is missing."
                ),
                prompt=json.dumps(
                    {"question": question, "entity_ids": entity_ids},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                max_tokens=4000,
                temperature=0,
                response_schema=DecomposedQuery.model_json_schema(),
            )
        )
        try:
            decomposition = DecomposedQuery.model_validate_json(response.text)
        except ValidationError as exc:
            raise ModelInvocationError("model returned an invalid query decomposition") from exc
        # An unregistered profile is dropped rather than executed. Naming a
        # profile is the one field where a plausible invention would otherwise
        # reach the scoring engine, so the allowlist is enforced here and again
        # against the live registry before anything is ranked.
        profile = decomposition.decision_profile
        if profile is not None and profile not in self._allowed_profiles:
            _LOGGER.warning("model proposed an unregistered decision profile: %s", profile)
            profile = None
        return Decomposition(
            query=decomposition.model_copy(
                update={
                    "original_question": question,
                    "entity_ids": entity_ids,
                    "decision_profile": profile,
                }
            ),
            source=DecompositionSource.MODEL,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    def _operation_glossary(self) -> str:
        """One line per operation this runtime can actually route.

        Only registered operations are listed. Naming an operation and then
        saying it is unavailable gives the model a choice it must not make, and
        in practice it reasons about the gap inside a free-text field until it
        exhausts the token budget.
        """

        described = {
            capability.operation: capability.description
            for capability in (self._capabilities.list() if self._capabilities else ())
        }
        if not described:
            return "\n".join(f"- {operation.value}" for operation in AnalysisOperation)
        return "\n".join(
            f"- {operation.value}: {described[operation]}"
            for operation in AnalysisOperation
            if operation in described
        )


class FallbackQueryDecomposer:
    """Use the keyword table only when the primary decomposer cannot answer.

    The fallback records why it fired on the ``Decomposition`` it returns, which
    is what makes the downgrade auditable. A model provider that is throttled,
    misconfigured, or returning malformed JSON otherwise looks identical to a
    working one: the answers stay grounded and correctly cited, they are just
    planned by keyword matching, and nothing in the response says so.
    """

    def __init__(self, primary: QueryDecomposer, fallback: QueryDecomposer) -> None:
        self._primary = primary
        self._fallback = fallback

    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> Decomposition:
        try:
            return await self._primary.decompose(question, entity_ids)
        except ModelInvocationError as exc:
            _LOGGER.warning("query decomposer fell back to the keyword table: %s", exc)
            degraded = await self._fallback.decompose(question, entity_ids)
            return degraded.model_copy(update={"degraded_reason": str(exc)[:300]})


class ToolCapabilityRegistry:
    """Registry searched by operation rather than hard-coded tool branching."""

    def __init__(self, capabilities: tuple[ToolCapability, ...] = ()) -> None:
        self._by_name: dict[str, ToolCapability] = {}
        self._by_operation: dict[AnalysisOperation, ToolCapability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: ToolCapability) -> None:
        if capability.name in self._by_name:
            raise ValueError(f"tool capability {capability.name!r} is already registered")
        if capability.operation in self._by_operation:
            raise ValueError(
                f"operation {capability.operation.value!r} already has a registered tool"
            )
        self._by_name[capability.name] = capability
        self._by_operation[capability.operation] = capability

    def for_operation(self, operation: AnalysisOperation) -> ToolCapability | None:
        return self._by_operation.get(operation)

    def list(self) -> tuple[ToolCapability, ...]:
        return tuple(self._by_name[name] for name in sorted(self._by_name))

    def search(self, operations: tuple[AnalysisOperation, ...]) -> tuple[ToolCapability, ...]:
        """Return only registered tools relevant to the requested operations."""

        requested = set(operations)
        return tuple(capability for capability in self.list() if capability.operation in requested)


class SmartToolRouter:
    """Route validated operations to capabilities and expose every missing tool."""

    def __init__(self, capabilities: ToolCapabilityRegistry) -> None:
        self._capabilities = capabilities

    def route(self, decomposition: DecomposedQuery) -> RoutedToolPlan:
        steps: list[RoutedToolStep] = []
        missing: list[AnalysisOperation] = []
        completed: set[AnalysisOperation] = set()
        for operation in dict.fromkeys(decomposition.operations):
            capability = self._capabilities.for_operation(operation)
            if capability is None or not set(capability.requires).issubset(completed):
                missing.append(operation)
                continue
            depends_on = tuple(
                step.step_id for step in steps if step.operation in capability.requires
            )
            steps.append(
                RoutedToolStep(
                    step_id=f"step_{len(steps) + 1}",
                    operation=operation,
                    tool_name=capability.name,
                    depends_on=depends_on,
                )
            )
            completed.add(operation)
        return RoutedToolPlan(steps=tuple(steps), missing_operations=tuple(missing))


def default_decision_capabilities() -> ToolCapabilityRegistry:
    """Capabilities implemented by the current feature-decision vertical slice."""

    return ToolCapabilityRegistry(
        (
            ToolCapability(
                name="search_tools",
                operation=AnalysisOperation.SEARCH_TOOLS,
                description="Find registered, bounded tools relevant to the analysis goal.",
            ),
            ToolCapability(
                name="search_catalog",
                operation=AnalysisOperation.SEARCH_CATALOG,
                description="Resolve registered semantic features and decision profiles.",
            ),
            ToolCapability(
                name="get_features",
                operation=AnalysisOperation.GET_FEATURES,
                description="Retrieve immutable feature values with evidence.",
                requires=(AnalysisOperation.SEARCH_CATALOG,),
            ),
            ToolCapability(
                name="rank_candidates",
                operation=AnalysisOperation.RANK_CANDIDATES,
                description="Apply registered constraints, weights, and deterministic scoring.",
                requires=(AnalysisOperation.GET_FEATURES,),
            ),
            ToolCapability(
                name="explain_lineage",
                operation=AnalysisOperation.EXPLAIN_LINEAGE,
                description="Project source evidence into public dataset-version citations.",
            ),
        )
    )


def register_observation_capabilities(registry: ToolCapabilityRegistry) -> None:
    """Add the generic curated-observation vertical slice to a runtime registry."""

    registry.register(
        ToolCapability(
            name="inspect_dataset",
            operation=AnalysisOperation.INSPECT_DATASET,
            description="Resolve schema, metric inventory, geography, and time coverage.",
            requires=(AnalysisOperation.SEARCH_CATALOG,),
        )
    )
    registry.register(
        ToolCapability(
            name="query_observations",
            operation=AnalysisOperation.QUERY_OBSERVATIONS,
            description="Run a validated read-only canonical observation query.",
            requires=(AnalysisOperation.INSPECT_DATASET,),
        )
    )
    registry.register(
        ToolCapability(
            name="compare_entities",
            operation=AnalysisOperation.COMPARE_ENTITIES,
            description="Calculate compatible entity changes without model arithmetic.",
            requires=(AnalysisOperation.QUERY_OBSERVATIONS,),
        )
    )
    registry.register(
        ToolCapability(
            name="join_observations",
            operation=AnalysisOperation.JOIN_OBSERVATIONS,
            description=(
                "Safely combine aggregated datasets on exact canonical entity and period keys."
            ),
            requires=(AnalysisOperation.QUERY_OBSERVATIONS,),
        )
    )


def register_forecast_capabilities(registry: ToolCapabilityRegistry) -> None:
    """Add retrieval of published forecast artifacts to a runtime registry."""

    registry.register(
        ToolCapability(
            name="forecast_metric",
            operation=AnalysisOperation.FORECAST_METRIC,
            description="Retrieve a published forecast with uncertainty and model lineage.",
            requires=(AnalysisOperation.INSPECT_DATASET,),
        )
    )


def register_acquisition_capabilities(registry: ToolCapabilityRegistry) -> None:
    """Advertise controlled source discovery and ingestion handoff capabilities."""

    registry.register(
        ToolCapability(
            name="discover_sources",
            operation=AnalysisOperation.DISCOVER_SOURCES,
            description="Find allowlisted external sources matching a bounded data requirement.",
        )
    )
    registry.register(
        ToolCapability(
            name="acquire_source",
            operation=AnalysisOperation.ACQUIRE_SOURCE,
            description="Snapshot one selected source into the approval-gated ingestion workflow.",
            requires=(AnalysisOperation.DISCOVER_SOURCES,),
        )
    )


def register_web_search_capabilities(registry: ToolCapabilityRegistry) -> None:
    """Advertise public-web lookup separately from catalog and source discovery."""

    registry.register(
        ToolCapability(
            name="web_search",
            operation=AnalysisOperation.SEARCH_WEB,
            description=(
                "Search the public web for current information and return URL-backed snippets."
            ),
        )
    )


def register_impact_capabilities(registry: ToolCapabilityRegistry) -> None:
    """Add the population-shock impact-chain tools to a runtime registry."""

    registry.register(
        ToolCapability(
            name="simulate_scenario",
            operation=AnalysisOperation.SIMULATE_SCENARIO,
            description=(
                "Project an explicit district youth-population shock against a cohort baseline."
            ),
            requires=(AnalysisOperation.SEARCH_CATALOG,),
        )
    )
    registry.register(
        ToolCapability(
            name="assess_capacity",
            operation=AnalysisOperation.ASSESS_CAPACITY,
            description=(
                "Test whether published infrastructure capacity metrics support impact estimates."
            ),
            requires=(AnalysisOperation.SIMULATE_SCENARIO,),
        )
    )
    registry.register(
        ToolCapability(
            name="recommend_investment",
            operation=AnalysisOperation.RECOMMEND_INVESTMENT,
            description="Rank investments only when the preceding capacity evidence is complete.",
            requires=(AnalysisOperation.ASSESS_CAPACITY,),
        )
    )


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _subject_terms(text: str) -> tuple[str, ...]:
    stopwords = {
        "a",
        "an",
        "and",
        "ở",
        "đâu",
        "i",
        "in",
        "is",
        "me",
        "nên",
        "should",
        "the",
        "tôi",
        "what",
        "where",
    }
    tokens = [token.strip("?!,.;:()") for token in text.split()]
    return tuple(
        dict.fromkeys(token for token in tokens if len(token) > 1 and token not in stopwords)
    )


_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "population_count": ("population", "dân số", "人口", "青年人口"),
    "employment_count": ("employment", "việc làm", "就業"),
    "unemployment_count": ("unemployment", "thất nghiệp", "失業"),
    "unemployment_rate": ("unemployment rate", "tỷ lệ thất nghiệp", "失業率"),
}
# A rate alias contains its count alias ("失業率" holds "失業"), so naming the rate
# must not also claim the count.
_RATE_OF_COUNT = {"unemployment_rate": "unemployment_count"}


def _metric_terms(text: str) -> tuple[str, ...]:
    """Name the canonical metrics a question asks for, matching whole words only.

    Substring matching cannot be used here: "employment" sits inside
    "unemployment", so "youth unemployment by district" claimed both metrics, and
    a downstream selector offered a choice the question never gave it. Latin
    aliases therefore need a word boundary on both sides. CJK aliases keep plain
    containment because those scripts are written without word separators.
    """

    named = [
        metric
        for metric, terms in _METRIC_ALIASES.items()
        if any(_names_metric(text, term) for term in terms)
    ]
    shadowed = {_RATE_OF_COUNT[metric] for metric in named if metric in _RATE_OF_COUNT}
    return tuple(metric for metric in named if metric not in shadowed)


def _names_metric(text: str, term: str) -> bool:
    if any("\u3400" <= character <= "\u9fff" for character in term):
        return term in text
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _time_expression(text: str) -> str | None:
    years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)
    relative = re.search(
        r"(?:last|past|trong)\s+\d+\s+(?:years?|năm)|\b\d+\s+năm\s+(?:qua|gần đây)"
        r"|(?:過去|最近)\s*\d+\s*年",
        text,
    )
    if relative:
        return relative.group(0)
    if years:
        return "-".join(years)
    return None
