"""Query decomposer and smart tool router behavior."""

import asyncio

from youth_compass.agent import (
    AnalysisOperation,
    Decomposition,
    DecompositionSource,
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
    async def decompose(self, question: str, entity_ids: tuple[str, ...]) -> Decomposition:
        del question, entity_ids
        raise ModelInvocationError("Bedrock unavailable")


def test_decomposer_splits_cross_district_trend_question() -> None:
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose(
            "So sánh xu hướng thất nghiệp ở Banqiao và Linkou",
            ("banqiao", "linkou"),
        )
    ).query

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
    ).query

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
    ).query

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
    ).query

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
    ).query

    assert decomposition.original_question == "Compare population"
    assert decomposition.entity_ids == ("banqiao",)
    assert decomposition.operations[-1] is AnalysisOperation.QUERY_OBSERVATIONS
    assert provider.requests[0].response_schema is not None


def test_model_decomposer_falls_back_to_the_keyword_table() -> None:
    decomposer = FallbackQueryDecomposer(FailingDecomposer(), DeterministicQueryDecomposer())

    result = asyncio.run(decomposer.decompose("Compare population trend", ("a", "b")))

    assert result.query.metric_terms == ("population_count",)
    assert AnalysisOperation.QUERY_OBSERVATIONS in result.query.operations


def test_the_fallback_reports_which_decomposer_actually_planned_the_turn() -> None:
    """Provenance travels with the plan, so a degraded turn cannot look healthy."""

    decomposer = FallbackQueryDecomposer(FailingDecomposer(), DeterministicQueryDecomposer())

    degraded = asyncio.run(decomposer.decompose("Compare population trend", ()))
    healthy = asyncio.run(DeterministicQueryDecomposer().decompose("Compare population trend", ()))

    assert degraded.source is DecompositionSource.KEYWORD_TABLE
    assert degraded.degraded_reason == "Bedrock unavailable"
    # The same decomposer reached directly is not a degradation: it is the
    # configured choice, so there is no reason to report.
    assert healthy.source is DecompositionSource.KEYWORD_TABLE
    assert healthy.degraded_reason is None


def test_the_model_decomposer_reports_itself_as_the_source() -> None:
    provider = StaticModelProvider(
        """{
          "original_question": "ignored",
          "objective": "compare population",
          "operations": ["search_catalog"]
        }"""
    )

    planned = asyncio.run(ModelQueryDecomposer(provider).decompose("Compare population", ()))

    assert planned.source is DecompositionSource.MODEL
    assert planned.degraded_reason is None


def test_unemployment_does_not_also_claim_the_employment_metric() -> None:
    """ "employment" sits inside "unemployment", so substring matching claimed both.

    Two canonical metrics on a question that named one handed the downstream
    metric selector a choice the question never offered, and the extra term let a
    mismatch look like a partial match.
    """

    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose(
            "Compare youth unemployment by district from 2023 to 2025", ()
        )
    ).query

    assert decomposition.metric_terms == ("unemployment_count",)


def test_employment_on_its_own_still_resolves() -> None:
    decomposition = asyncio.run(
        DeterministicQueryDecomposer().decompose("Show the employment trend", ())
    ).query

    assert decomposition.metric_terms == ("employment_count",)


def test_metric_aliases_still_match_vietnamese_and_chinese_spellings() -> None:
    """CJK is written without word separators, so those aliases stay containment."""

    zh = asyncio.run(DeterministicQueryDecomposer().decompose("查看青年失業趨勢", ())).query
    vi = asyncio.run(
        DeterministicQueryDecomposer().decompose("Xu hướng thất nghiệp thanh niên", ())
    ).query

    assert zh.metric_terms == ("unemployment_count",)
    assert vi.metric_terms == ("unemployment_count",)
