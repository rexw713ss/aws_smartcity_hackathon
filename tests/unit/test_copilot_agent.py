"""Grounded copilot planning, scoring, and refusal behavior."""

import asyncio
from datetime import UTC, datetime

import pytest

from youth_compass.agent import (
    AnswerCompositionContext,
    ComposedAnswer,
    CopilotStatus,
    DeterministicCopilotPlanner,
    GroundedCopilotService,
    ModelCopilotPlanner,
)
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
    assert [trace.tool for trace in response.tool_trace] == [
        "query_decomposer",
        "search_catalog",
        "get_features",
        "rank_candidates",
        "explain_lineage",
        "answer_composer",
        "visualization_builder",
    ]
    assert set(provider.queries[0].feature_codes) == {
        "property_cost",
        "transit_accessibility",
        "amenity_accessibility",
        "environmental_risk",
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
    assert response.tool_trace[-2].tool == "answer_composer"
    assert response.tool_trace[-2].outcome == "model"
    assert response.tool_trace[-1].tool == "visualization_builder"


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


def test_model_planner_is_schema_constrained_and_profile_allowlisted() -> None:
    provider = StaticModelProvider('{"profile_code":"home_buying","entity_ids":["model-invented"]}')
    planner = ModelCopilotPlanner(provider)

    intent = asyncio.run(planner.plan("Help me choose a home", ("banqiao",)))

    assert intent is not None
    assert intent.profile_code == "home_buying"
    assert intent.entity_ids == ("banqiao",)
    assert provider.requests[0].temperature == 0
    assert provider.requests[0].response_schema is not None


def test_model_planner_rejects_unregistered_profile() -> None:
    provider = StaticModelProvider('{"profile_code":"secret_admin_tool","entity_ids":[]}')

    intent = asyncio.run(ModelCopilotPlanner(provider).plan("Do something", ()))

    assert intent is None


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
def test_deterministic_planner_evaluation_set(question: str, expected: str | None) -> None:
    intent = asyncio.run(DeterministicCopilotPlanner().plan(question, ()))

    assert (intent.profile_code if intent else None) == expected
