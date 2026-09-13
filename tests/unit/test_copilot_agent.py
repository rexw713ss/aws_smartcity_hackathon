"""Grounded copilot planning, scoring, and refusal behavior."""

import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent import (
    AnalysisOperation,
    AnswerCompositionContext,
    ComposedAnswer,
    ConversationContext,
    CopilotStatus,
    DeterministicQueryDecomposer,
    GroundedCopilotService,
    ModelQueryDecomposer,
)
from youth_compass.agent.service import _question_with_topic_hint
from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    DecisionProfileRegistry,
    FeatureEvidence,
    FeatureQuery,
    FeatureRegistry,
    FeatureSet,
    FeatureValue,
)
from youth_compass.domain.errors import ConversationPersistenceError, SourceAcquisitionError
from youth_compass.ports import ModelRequest, ModelResponse


class StaticFeatureProvider:
    def __init__(self, values: tuple[FeatureValue, ...]) -> None:
        self.values = values
        self.queries: list[FeatureQuery] = []

    def get_features(self, query: FeatureQuery) -> FeatureSet:
        self.queries.append(query)
        values = tuple(
            value
            for value in self.values
            if value.feature_code in query.feature_codes
            and (not query.entity_ids or value.entity_id in query.entity_ids)
            and min(item.quality_score for item in value.evidence) >= query.min_quality_score
        )
        return FeatureSet(values=values)


class StaticModelProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=self.text, model_id="bedrock-test")


class RecordingAnswerComposer:
    def __init__(self) -> None:
        self.contexts: list[AnswerCompositionContext] = []

    async def compose(self, context: AnswerCompositionContext) -> ComposedAnswer:
        self.contexts.append(context)
        return ComposedAnswer(
            answer="Banqiao là lựa chọn phù hợp nhất.",
            citation_ids=(),
            mode="model",
        )


def test_selected_topic_scopes_a_generic_question_without_overriding_an_explicit_topic() -> None:
    assert _question_with_topic_hint("Give me an overview", "population") == (
        "Give me an overview\nDataset topic: population"
    )
    assert _question_with_topic_hint("Show the employment trend", "population") == (
        "Show the employment trend"
    )


def test_topic_overview_queries_observations_instead_of_listing_the_catalog() -> None:
    question = _question_with_topic_hint("Give me an overview", "education")
    planned = asyncio.run(DeterministicQueryDecomposer().decompose(question, ())).query

    assert planned.needs_clarification is False
    assert planned.objective == "summarize published observations"
    assert planned.operations == (
        AnalysisOperation.SEARCH_CATALOG,
        AnalysisOperation.INSPECT_DATASET,
        AnalysisOperation.QUERY_OBSERVATIONS,
        AnalysisOperation.EXPLAIN_LINEAGE,
    )


def _value(entity: str, feature: str, value: float, *, quality: float = 0.9) -> FeatureValue:
    return FeatureValue(
        entity_id=entity,
        feature_code=feature,
        value=value,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        evidence=(
            FeatureEvidence(
                dataset_id=f"{feature}_dataset",
                dataset_version="2026-09",
                source_uri=f"file:///private/data/{feature}.parquet",
                quality_score=quality,
                retrieved_at=datetime(2026, 9, 2, tzinfo=UTC),
            ),
        ),
    )


def _service(
    values: tuple[FeatureValue, ...],
) -> tuple[GroundedCopilotService, StaticFeatureProvider]:
    provider = StaticFeatureProvider(values)
    return (
        GroundedCopilotService(
            feature_provider=provider,
            feature_registry=FeatureRegistry(DEFAULT_FEATURES),
            profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        ),
        provider,
    )


def test_home_question_ranks_with_citations_and_no_storage_uri_leak() -> None:
    service, provider = _service(
        tuple(
            _value(entity, feature, value)
            for entity, readings in {
                "banqiao": {
                    "property_cost": 80,
                    "transit_accessibility": 90,
                    "amenity_accessibility": 85,
                    "environmental_risk": 20,
                },
                "linkou": {
                    "property_cost": 60,
                    "transit_accessibility": 70,
                    "amenity_accessibility": 65,
                    "environmental_risk": 40,
                },
            }.items()
            for feature, value in readings.items()
        )
    )

    response = asyncio.run(service.answer("Tôi nên mua nhà ở đâu?"))

    assert response.status is CopilotStatus.ANSWERED
    assert response.plan is not None and response.plan.profile_code == "home_buying"
    assert response.candidates[0].entity_id == "banqiao"
    assert response.candidates[0].rank == 1
    serialized = response.model_dump_json()
    assert "file:///" not in serialized
    assert response.citations
    assert all(citation.excerpt for citation in response.citations)
    assert {
        (row.entity_id, row.metric_code, row.value)
        for citation in response.citations
        for row in citation.excerpt
    } >= {
        ("banqiao", "property_cost", 80),
        ("linkou", "property_cost", 60),
    }
    assert [trace.tool for trace in response.tool_trace] == [
        "query_decomposer",
        # The single classifier proposes a profile name; the registry decides
        # whether this runtime has it. That check is recorded because it is the
        # step that can refuse an otherwise well-formed decision question.
        "resolve_decision_profile",
        "search_catalog",
        "get_features",
        "rank_candidates",
        "explain_lineage",
        "answer_composer",
        "visualization_builder",
        "audit_limitations",
    ]
    assert response.limitations is not None
    assert "Lý do chính là" in response.answer
    assert "[data-" in response.answer
    assert "Lâm Khẩu" in response.answer
    assert "điểm đóng góp" in response.answer
    assert set(provider.queries[0].feature_codes) == {
        "property_cost",
        "transit_accessibility",
        "amenity_accessibility",
        "environmental_risk",
    }


def test_decision_fallback_explains_ranking_without_requiring_a_chart() -> None:
    service, _ = _service(
        tuple(
            _value(entity, feature, value)
            for entity, readings in {
                "banqiao": {
                    "property_cost": 80,
                    "transit_accessibility": 90,
                    "amenity_accessibility": 85,
                    "environmental_risk": 20,
                },
                "linkou": {
                    "property_cost": 60,
                    "transit_accessibility": 70,
                    "amenity_accessibility": 65,
                    "environmental_risk": 40,
                },
            }.items()
            for feature, value in readings.items()
        )
    )

    response = asyncio.run(service.answer("Where should I buy a home?"))

    assert "The main reason is" in response.answer
    assert "runner-up Linkou" in response.answer
    assert "contribution points" in response.answer
    assert "[data-" in response.answer
    assert "Review the feature contributions" not in response.answer


def test_a_slug_candidate_is_answered_under_a_readable_name() -> None:
    values = []
    for feature, value in {
        "ev_demand_proxy": 80,
        "transit_accessibility": 60,
        "parking_availability": 70,
        "grid_accessibility": 90,
        "charger_competition": 20,
        "site_feasibility": 1,
    }.items():
        values.append(_value("site-linkou-center", feature, value))
    service, _ = _service(tuple(values))

    response = asyncio.run(service.answer("Where should we place an EV charging station?"))

    assert response.status is CopilotStatus.ANSWERED
    top = response.candidates[0]
    assert top.entity_id == "site-linkou-center"
    assert top.entity_name == "Linkou Center"
    assert "site-linkou-center" not in response.answer
    assert {item.feature_name for item in top.contributions} == {
        "EV demand proxy",
        "Transit accessibility",
        "Parking availability",
        "Grid accessibility",
        "Charger competition",
    }


def test_charger_question_applies_feasibility_constraint() -> None:
    values = []
    for entity, feasibility in (("site-a", 1), ("site-b", 0)):
        for feature, value in {
            "ev_demand_proxy": 80,
            "transit_accessibility": 60,
            "parking_availability": 70,
            "grid_accessibility": 90,
            "charger_competition": 20,
            "site_feasibility": feasibility,
        }.items():
            values.append(_value(entity, feature, value))
    service, _ = _service(tuple(values))

    response = asyncio.run(service.answer("Nên đặt trụ sạc xe ở đâu?"))

    assert response.status is CopilotStatus.ANSWERED
    assert response.plan is not None
    assert response.plan.profile_code == "ev_charger_placement"
    assert response.candidates[0].entity_id == "site-a"
    assert response.candidates[1].eligible is False
    assert "site_feasibility" in response.candidates[1].failed_constraints[0]


def test_service_composes_only_public_grounded_decision_facts() -> None:
    feature_provider = StaticFeatureProvider(
        tuple(
            _value("banqiao", feature, value)
            for feature, value in {
                "property_cost": 80,
                "transit_accessibility": 90,
                "amenity_accessibility": 85,
                "environmental_risk": 20,
            }.items()
        )
    )
    composer = RecordingAnswerComposer()
    service = GroundedCopilotService(
        feature_provider=feature_provider,
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        answer_composer=composer,
    )

    response = asyncio.run(service.answer("Tôi nên mua nhà ở đâu?"))

    assert response.answer == "Banqiao là lựa chọn phù hợp nhất."
    assert len(composer.contexts) == 1
    assert composer.contexts[0].analysis_type == "decision"
    assert "file:///" not in composer.contexts[0].grounded_facts_json
    assert response.tool_trace[-3].tool == "answer_composer"
    assert response.tool_trace[-3].outcome == "model"
    assert response.tool_trace[-2].tool == "visualization_builder"
    assert response.tool_trace[-1].tool == "audit_limitations"


def test_unsupported_question_does_not_query_data() -> None:
    service, provider = _service(())

    response = asyncio.run(service.answer("What will the weather be tomorrow?"))

    assert response.status is CopilotStatus.UNSUPPORTED_QUESTION
    assert provider.queries == []
    assert response.citations == ()


def test_missing_or_low_quality_data_refuses_to_rank() -> None:
    service, provider = _service((_value("banqiao", "property_cost", 80, quality=0.4),))

    response = asyncio.run(service.answer("Where should I buy a home?", min_quality_score=0.8))

    assert response.status is CopilotStatus.INSUFFICIENT_DATA
    assert response.candidates == ()
    assert provider.queries[0].min_quality_score == 0.8


def test_a_decision_profile_this_runtime_lacks_is_refused_not_ranked() -> None:
    """The registry is the last word on which profiles exist.

    A single classifier means the profile name arrives with the plan rather than
    from a second model call that already checked an allowlist. The runtime must
    therefore still verify it, and say so: a deployment that registered no
    charger profile has to refuse a charger question rather than rank it with
    whatever profile it does have.
    """

    provider = StaticFeatureProvider(())
    service = GroundedCopilotService(
        feature_provider=provider,
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(
            tuple(
                item
                for item in DEFAULT_DECISION_PROFILES
                if item.profile_code != "ev_charger_placement"
            )
        ),
    )

    response = asyncio.run(service.answer("Nên đặt trụ sạc xe ở đâu?"))

    assert response.status is CopilotStatus.UNSUPPORTED_QUESTION
    assert response.decomposition is not None
    assert response.decomposition.decision_profile == "ev_charger_placement"
    assert response.candidates == ()
    assert provider.queries == [], "no feature was retrieved for an unrunnable profile"
    refusal = next(item for item in response.tool_trace if item.tool == "resolve_decision_profile")
    assert refusal.outcome == "unsupported"
    assert "ev_charger_placement" in refusal.summary
    assert "home_buying" in refusal.summary


def test_the_decomposer_classifies_the_decision_profile_and_keeps_user_scope() -> None:
    """One classifier names the profile, and it cannot overwrite the caller's scope."""

    provider = StaticModelProvider(
        """{
          "original_question": "model rewrite",
          "objective": "rank candidates for a location decision",
          "operations": ["search_catalog", "get_features", "rank_candidates"],
          "decision_profile": "home_buying",
          "entity_ids": ["model-invented"]
        }"""
    )

    planned = asyncio.run(
        ModelQueryDecomposer(provider).decompose("Help me choose a home", ("banqiao",))
    )

    assert planned.query.decision_profile == "home_buying"
    assert planned.query.entity_ids == ("banqiao",)
    assert provider.requests[0].temperature == 0
    assert provider.requests[0].response_schema is not None


def test_the_decomposer_drops_a_decision_profile_outside_the_allowlist() -> None:
    """A profile name is the one field where a plausible invention would execute."""

    provider = StaticModelProvider(
        """{
          "original_question": "ignored",
          "objective": "rank candidates",
          "operations": ["search_catalog", "get_features", "rank_candidates"],
          "decision_profile": "secret_admin_tool"
        }"""
    )

    planned = asyncio.run(ModelQueryDecomposer(provider).decompose("Do something", ()))

    assert planned.query.decision_profile is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Tôi nên mua nhà ở đâu?", "home_buying"),
        ("Giúp tôi chọn nơi mua nhà", "home_buying"),
        ("Nhà ở đâu phù hợp nhất?", "home_buying"),
        ("Where should I buy a home?", "home_buying"),
        ("Help with home buying", "home_buying"),
        ("Recommend a buy house location", "home_buying"),
        ("Compare housing location options", "home_buying"),
        ("MUA NHÀ ở khu vực nào", "home_buying"),
        ("Nên đặt trụ sạc xe ở đâu?", "ev_charger_placement"),
        ("Tìm vị trí trạm sạc", "ev_charger_placement"),
        ("Dat tru sac tai khu nao", "ev_charger_placement"),
        ("Where should we place an EV charger?", "ev_charger_placement"),
        ("Rank charging station sites", "ev_charger_placement"),
        ("Run the charger placement model", "ev_charger_placement"),
        ("Compare tram sac candidates", "ev_charger_placement"),
        ("TRỤ SẠC nào phù hợp", "ev_charger_placement"),
        ("What is tomorrow's weather?", None),
        ("Summarize the latest population", None),
        ("Delete a dataset", None),
        ("Write arbitrary SQL", None),
    ],
)
def test_keyword_decomposer_decision_profile_evaluation_set(
    question: str, expected: str | None
) -> None:
    """The profile now rides on the decomposition instead of a parallel intent."""

    decomposition = asyncio.run(DeterministicQueryDecomposer().decompose(question, ())).query

    assert decomposition.decision_profile == expected
    # A profile and a ranking plan must agree: the profile is what the ranking
    # executes, so one without the other is a plan nothing can run.
    assert (AnalysisOperation.RANK_CANDIDATES in decomposition.operations) is (expected is not None)


class FailingConversationStore:
    """A durable store that is unreachable, as a remote store can be."""

    def __init__(self) -> None:
        self.writes = 0

    def get(self, session_id: str) -> ConversationContext | None:
        raise ConversationPersistenceError("cannot read conversation context")

    def put(self, context: ConversationContext) -> None:
        self.writes += 1
        raise ConversationPersistenceError("cannot persist conversation context")


_HOME_FEATURES = tuple(
    _value(entity, feature, value)
    for entity, readings in {
        "banqiao": {
            "property_cost": 80,
            "transit_accessibility": 90,
            "amenity_accessibility": 85,
            "environmental_risk": 20,
        },
    }.items()
    for feature, value in readings.items()
)


def test_an_unreachable_conversation_store_never_fails_the_turn() -> None:
    # Losing inherited scope degrades a follow-up; failing the request would
    # take down every answer whenever the session table is unavailable. Both
    # the read and the write are exercised: this question does answer.
    store = FailingConversationStore()
    service = GroundedCopilotService(
        feature_provider=StaticFeatureProvider(_HOME_FEATURES),
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        conversation_store=store,
    )

    response = asyncio.run(service.answer("Tôi nên mua nhà ở đâu?"))

    assert response.status is CopilotStatus.ANSWERED
    assert response.session_id is not None
    assert store.writes == 1


class RecordingConversationStore:
    def __init__(self) -> None:
        self.stored: list[ConversationContext] = []

    def get(self, session_id: str) -> ConversationContext | None:
        return self.stored[-1] if self.stored else None

    def put(self, context: ConversationContext) -> None:
        self.stored.append(context)


def test_a_scope_that_found_no_evidence_is_not_remembered() -> None:
    # Remembering a failed scope would make every later turn in the session
    # inherit it, so the session could never answer anything again.
    store = RecordingConversationStore()
    service = GroundedCopilotService(
        feature_provider=StaticFeatureProvider(()),
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        conversation_store=store,
    )

    response = asyncio.run(service.answer("Where should I buy a home?"))

    assert response.status is not CopilotStatus.ANSWERED
    assert store.stored == []


class FailingAcquisitionService:
    """Discovery that cannot reach its connectors."""

    def discover(self, requirement: object) -> tuple[object, ...]:
        raise SourceAcquisitionError("source registry is unreachable")


def test_a_failed_source_search_is_reported_as_an_outage_not_as_no_sources() -> None:
    # An empty candidate list alone cannot distinguish "searched, found none"
    # from "could not search", and only the first justifies telling the user
    # that no suitable source exists.
    provider = StaticFeatureProvider(())
    service = GroundedCopilotService(
        feature_provider=provider,
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        acquisition=cast("DataAcquisitionService", FailingAcquisitionService()),
    )

    response = asyncio.run(service.answer("Where should I buy a home?"))

    assert response.status is CopilotStatus.INSUFFICIENT_DATA
    assert response.source_candidates == ()
    assert any("Source discovery was unavailable" in warning for warning in response.warnings)
    assert "could not run" in response.answer
    assert any(
        item.tool == "discover_sources" and item.outcome == "failed" for item in response.tool_trace
    )
