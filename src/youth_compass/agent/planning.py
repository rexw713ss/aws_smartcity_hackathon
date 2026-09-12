"""Query decomposition, capability discovery, and deterministic tool routing."""

import json
import re
from typing import Protocol

from pydantic import ValidationError

from youth_compass.agent.contracts import (
    AnalysisOperation,
    DecomposedQuery,
    RoutedToolPlan,
    RoutedToolStep,
    ToolCapability,
)
from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ports import ModelProvider, ModelRequest


class QueryDecomposer(Protocol):
    """Turn a question into generic, schema-validated analysis operations."""

    async def decompose(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> DecomposedQuery:
        """Return a decomposition without executing any tool."""
        ...


class DeterministicQueryDecomposer:
    """Offline decomposition for common discovery, analysis, and decision shapes."""

    async def decompose(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> DecomposedQuery:
        normalized = " ".join(question.casefold().split())
        decision = _contains(
            normalized,
            "mua nhà",
            "nhà ở đâu",
            "buy a home",
            "buy house",
            "home buying",
            "housing location",
            "trụ sạc",
            "trạm sạc",
            "tru sac",
            "tram sac",
            "ev charger",
            "charging station",
            "charger placement",
        )
        compare = _contains(normalized, "compare", "so sánh", "khác nhau", "versus", " vs ")
        trend = _contains(normalized, "trend", "xu hướng", "tăng", "giảm", "over time")
        forecast = _contains(normalized, "forecast", "dự báo", "predict", "tương lai")
        discover = _contains(
            normalized,
            "dataset",
            "data source",
            "nguồn dữ liệu",
            "dữ liệu nào",
            "what data",
        )

        operations: list[AnalysisOperation] = [AnalysisOperation.SEARCH_CATALOG]
        objective = "discover relevant evidence"
        needs_clarification = False
        clarification_question = None
        if decision:
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
        elif trend or compare:
            objective = "compare observations" if compare else "analyze a time trend"
            operations.extend(
                (AnalysisOperation.INSPECT_DATASET, AnalysisOperation.QUERY_OBSERVATIONS)
            )
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
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
        )


class ModelQueryDecomposer:
    """Schema-constrained decomposer for a Bedrock-backed ModelProvider."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def decompose(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> DecomposedQuery:
        response = await self._provider.generate(
            ModelRequest(
                system=(
                    "Decompose the question into safe analysis operations. Return only JSON "
                    "matching the schema. Do not name tools, SQL, tables, or storage paths."
                ),
                prompt=json.dumps(
                    {"question": question, "entity_ids": entity_ids},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                max_tokens=600,
                temperature=0,
                response_schema=DecomposedQuery.model_json_schema(),
            )
        )
        try:
            decomposition = DecomposedQuery.model_validate_json(response.text)
        except ValidationError as exc:
            raise ModelInvocationError("model returned an invalid query decomposition") from exc
        return decomposition.model_copy(
            update={"original_question": question, "entity_ids": entity_ids}
        )


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


def _metric_terms(text: str) -> tuple[str, ...]:
    aliases = {
        "population_count": ("population", "dân số"),
        "unemployment_count": ("unemployment", "thất nghiệp"),
    }
    return tuple(
        metric
        for metric, terms in aliases.items()
        if any(term in text for term in terms)
    )


def _time_expression(text: str) -> str | None:
    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    relative = re.search(
        r"(?:last|past|trong)\s+\d+\s+(?:years?|năm)|\b\d+\s+năm\s+(?:qua|gần đây)",
        text,
    )
    if relative:
        return relative.group(0)
    if years:
        return "-".join(years)
    return None
