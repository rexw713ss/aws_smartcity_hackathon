"""Deterministic, evidence-grounded copilot orchestration."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from youth_compass.agent.contracts import (
    CandidateInsight,
    CopilotIntent,
    CopilotResponse,
    CopilotStatus,
    DecisionExecutionPlan,
    DecomposedQuery,
    EvidenceCitation,
    FeatureContributionInsight,
    RoutedToolPlan,
    ToolCapability,
    ToolTrace,
)
from youth_compass.agent.planning import (
    DeterministicQueryDecomposer,
    QueryDecomposer,
    SmartToolRouter,
    ToolCapabilityRegistry,
    default_decision_capabilities,
)
from youth_compass.decisioning import (
    CandidateScore,
    DecisionProfileRegistry,
    DecisionScoringEngine,
    FeatureProvider,
    FeatureQuery,
    FeatureRegistry,
    FeatureValue,
)
from youth_compass.domain.errors import ModelInvocationError, QueryExecutionError
from youth_compass.ports import ModelProvider, ModelRequest


class CopilotPlanner(Protocol):
    """Convert natural language into an allowlisted, schema-validated intent."""

    async def plan(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> CopilotIntent | None:
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
    )
    _CHARGER_TERMS = (
        "trụ sạc",
        "trạm sạc",
        "tru sac",
        "tram sac",
        "ev charger",
        "charging station",
        "charger placement",
    )

    async def plan(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> CopilotIntent | None:
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

    async def plan(
        self, question: str, entity_ids: tuple[str, ...]
    ) -> CopilotIntent | None:
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
    ) -> None:
        self._provider = feature_provider
        self._features = feature_registry
        self._profiles = profile_registry
        self._planner = planner or DeterministicCopilotPlanner()
        self._decomposer = decomposer or DeterministicQueryDecomposer()
        self._capabilities = capabilities or default_decision_capabilities()
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
            missing_capabilities = tuple(
                item.value for item in routed_plan.missing_operations
            )
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
            missing_summary = ", ".join(
                item.value for item in routed_plan.missing_operations
            )
            return CopilotResponse(
                status=CopilotStatus.INSUFFICIENT_DATA,
                answer=(
                    "The validated plan cannot run because tools are missing: "
                    f"{missing_summary}."
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
        answer = (
            f"{top.entity_name or top.entity_id} ranks first for "
            f"{profile.display_name} with a deterministic score of {top.score:.1f}/100. "
            "Review the feature contributions and cited dataset versions before making a decision."
        )
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
        )

    @staticmethod
    def _insufficient(
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
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer="There is not enough validated feature data to produce a grounded ranking.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            plan=plan,
            candidates=candidates,
            citations=citations,
            tool_trace=tuple(trace),
            warnings=warnings,
        )


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
