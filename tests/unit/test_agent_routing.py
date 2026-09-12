"""Query decomposer and smart tool router behavior."""

import asyncio

from youth_compass.agent import (
    AnalysisOperation,
    DecomposedQuery,
    DeterministicQueryDecomposer,
    FallbackQueryDecomposer,
    ModelQueryDecomposer,
    SmartToolRouter,
    ToolCapability,
    default_decision_capabilities,
    register_acquisition_capabilities,
    register_impact_capabilities,
)
from youth_compass.domain import ModelInvocationError
from youth_compass.ports import ModelRequest, ModelResponse


class StaticModelProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=self.response, model_id="bedrock-test")


class FailingDecomposer:
    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> DecomposedQuery:
        del question, entity_ids
        raise ModelInvocationError("Bedrock unavailable")


def test_decomposer_splits_cross_district_trend_question() -> None:
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose(
            "So sánh xu hướng thất nghiệp ở Banqiao và Linkou",
            ("banqiao", "linkou"),
        )
    )

    assert decomposition.objective == "compare observations"
    assert decomposition.entity_ids == ("banqiao", "linkou")
    assert decomposition.operations == (
        AnalysisOperation.SEARCH_CATALOG,
        AnalysisOperation.INSPECT_DATASET,
        AnalysisOperation.QUERY_OBSERVATIONS,
        AnalysisOperation.COMPARE_ENTITIES,
        AnalysisOperation.EXPLAIN_LINEAGE,
    )


def test_router_exposes_missing_generic_tools_instead_of_guessing() -> None:
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose("Forecast youth population", ())
    )

    plan = SmartToolRouter(default_decision_capabilities()).route(decomposition)

    assert [step.tool_name for step in plan.steps] == ["search_catalog", "explain_lineage"]
    assert plan.missing_operations == (
        AnalysisOperation.INSPECT_DATASET,
        AnalysisOperation.FORECAST_METRIC,
    )
    assert plan.executable is False


def test_what_if_question_searches_and_routes_impact_tools_in_dependency_order() -> None:
    capabilities = default_decision_capabilities()
    register_acquisition_capabilities(capabilities)
    register_impact_capabilities(capabilities)
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose(
            "Nếu thêm 2.000 thanh niên chuyển đến Linkou trước 2030, nên đầu tư hạ tầng gì?",
            ("17",),
        )
    )

    plan = SmartToolRouter(capabilities).route(decomposition)

    assert plan.executable is True
    assert decomposition.operations[0] is AnalysisOperation.SEARCH_TOOLS
    assert [step.tool_name for step in plan.steps] == [
        "search_tools",
        "search_catalog",
        "simulate_scenario",
        "assess_capacity",
        "discover_sources",
        "recommend_investment",
        "explain_lineage",
    ]
    assert [item.name for item in capabilities.search(decomposition.operations)] == [
        "assess_capacity",
        "discover_sources",
        "explain_lineage",
        "recommend_investment",
        "search_catalog",
        "search_tools",
        "simulate_scenario",
    ]


def test_new_capabilities_are_discovered_without_router_conditionals() -> None:
    capabilities = default_decision_capabilities()
    capabilities.register(
        ToolCapability(
            name="inspect_dataset",
            operation=AnalysisOperation.INSPECT_DATASET,
            description="Inspect schema and coverage.",
            requires=(AnalysisOperation.SEARCH_CATALOG,),
        )
    )
    capabilities.register(
        ToolCapability(
            name="query_observations",
            operation=AnalysisOperation.QUERY_OBSERVATIONS,
            description="Run a validated aggregate observation query.",
            requires=(AnalysisOperation.INSPECT_DATASET,),
        )
    )
    capabilities.register(
        ToolCapability(
            name="compare_entities",
            operation=AnalysisOperation.COMPARE_ENTITIES,
            description="Compare compatible entity observations.",
            requires=(AnalysisOperation.QUERY_OBSERVATIONS,),
        )
    )
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose(
            "So sánh xu hướng dân số giữa hai quận",
            ("district-a", "district-b"),
        )
    )

    plan = SmartToolRouter(capabilities).route(decomposition)

    assert plan.executable is True
    assert [step.tool_name for step in plan.steps] == [
        "search_catalog",
        "inspect_dataset",
        "query_observations",
        "compare_entities",
        "explain_lineage",
    ]
    assert plan.steps[2].depends_on == ("step_2",)


def test_model_decomposer_is_schema_constrained_and_preserves_user_scope() -> None:
    provider = StaticModelProvider(
        """{
          "original_question": "model rewrite",
          "objective": "compare population",
          "subject_terms": ["population"],
          "metric_terms": ["population_count"],
          "entity_ids": ["invented"],
          "operations": ["search_catalog", "inspect_dataset", "query_observations"],
          "needs_clarification": false
        }"""
    )

    decomposition = asyncio.run(
        ModelQueryDecomposer(provider).decompose(
            "Compare population",
            ("banqiao",),
        )
    )

    assert decomposition.original_question == "Compare population"
    assert decomposition.entity_ids == ("banqiao",)
    assert decomposition.operations[-1] is AnalysisOperation.QUERY_OBSERVATIONS
    assert provider.requests[0].response_schema is not None


def test_model_decomposer_falls_back_to_deterministic_planning() -> None:
    decomposer = FallbackQueryDecomposer(FailingDecomposer(), DeterministicQueryDecomposer())

    result = asyncio.run(decomposer.decompose("Compare population trend", ("a", "b")))

    assert result.metric_terms == ("population_count",)
    assert AnalysisOperation.QUERY_OBSERVATIONS in result.operations
