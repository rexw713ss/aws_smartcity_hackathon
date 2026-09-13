"""The decision-ranking pipeline: profile weights over retrieved features.

A location decision ("where should I buy a home?") is answered by a registered
decision profile, never by the model: the profile owns the weights and the hard
constraints, the feature store owns the values and their evidence, and this
module only executes the two against each other. Candidates missing a required
feature come back ineligible with the reason attached, and a ranking that cannot
be produced becomes a data-gap response rather than a guess.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime

from youth_compass.agent.contracts import (
    AnswerCompositionContext,
    CandidateInsight,
    CopilotResponse,
    CopilotStatus,
    DecisionExecutionPlan,
    DecomposedQuery,
    EvidenceCitation,
    EvidenceExcerptRow,
    FeatureContributionInsight,
    RoutedToolPlan,
    ToolTrace,
)
from youth_compass.agent.support import (
    AnswerSupport,
    answered,
    data_gap_answer,
    discovery_warning,
    grounded_json,
    inline_citations,
    name_language,
    response_language_for_fallback,
    unavailable_trace,
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
from youth_compass.domain.errors import QueryExecutionError
from youth_compass.ontology import readable_entity_name, readable_feature_name


class DecisionAnswering:
    """Rank a decision profile's candidates from published feature evidence."""

    def __init__(
        self,
        *,
        feature_provider: FeatureProvider,
        feature_registry: FeatureRegistry,
        profile_registry: DecisionProfileRegistry,
        support: AnswerSupport,
    ) -> None:
        self._provider = feature_provider
        self._features = feature_registry
        self._profiles = profile_registry
        self._support = support
        self._scorer = DecisionScoringEngine(feature_registry)

    async def rank(
        self,
        question: str,
        *,
        now: datetime,
        profile_code: str,
        decomposition: DecomposedQuery,
        routed_plan: RoutedToolPlan,
        trace: list[ToolTrace],
        min_quality_score: float,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> CopilotResponse:
        """Score a registered profile's candidates over retrieved feature values.

        Nothing is ranked from a model's opinion: the profile supplies weights
        and constraints, the feature store supplies values with their evidence,
        and a candidate missing a required feature is reported as ineligible
        rather than scored on what happens to be present.
        """

        profile = self._profiles.get(profile_code)
        # The scope a decision ranks over comes from the decomposition, which is
        # the only classification of this question. `_scope_from_question`
        # deliberately never narrows a ranking plan to districts, so this is the
        # caller-supplied entity set or nothing.
        entity_ids = decomposition.entity_ids
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
            entity_ids=entity_ids,
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
                    entity_ids=entity_ids,
                    min_quality_score=min_quality_score,
                )
            )
        except (QueryExecutionError, KeyError, ValueError) as exc:
            trace.append(unavailable_trace("get_features", exc))
            return self.insufficient(
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
            return self.insufficient(
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
            return self.insufficient(
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
            return self.insufficient(
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
        answer = await self._support.compose(
            AnswerCompositionContext(
                question=question,
                analysis_type="decision",
                grounded_facts_json=grounded_json(
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
            on_text=on_text,
        )
        visualizations = self._support.visualizations.decision(
            question,
            candidates,
            tuple(item.citation_id for item in citations),
        )
        self._support.trace_visualizations(trace, visualizations)
        limitations = self._support.limitations.build(
            now=now,
            citations=citations,
            observed_entity_ids=[candidate.entity_id for candidate in candidates],
            # A location decision is scored over whichever candidates the
            # profile supplied, so the district set is not the denominator.
            requested_entity_ids=[candidate.entity_id for candidate in candidates],
            catalog_terms=plan.feature_codes,
        )
        self._support.trace_limitations(trace, limitations)
        return answered(
            answer=answer,
            now=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            trace=trace,
            plan=plan,
            candidates=candidates,
            citations=citations,
            assumptions=(
                f"Weights and constraints come from {profile.profile_code}@{profile.version}.",
                "Scores compare only the candidates present in the retrieved feature snapshot.",
            ),
            warnings=tuple(warnings),
            visualizations=visualizations,
            limitations=limitations,
        )

    def insufficient(
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
        requirement, source_candidates, discovery_error = self._support.discover_sources(
            decomposition, trace, metric_codes=plan.feature_codes
        )
        visualizations = self._support.visualizations.decision(
            decomposition.original_question,
            candidates,
            tuple(item.citation_id for item in citations),
        )
        self._support.trace_visualizations(trace, visualizations)
        return CopilotResponse(
            status=(
                CopilotStatus.ACQUISITION_REQUIRED
                if source_candidates
                else CopilotStatus.INSUFFICIENT_DATA
            ),
            answer=data_gap_answer(
                decomposition.original_question,
                source_candidates,
                "There is not enough validated feature data to produce a grounded ranking.",
                discovery_failed=discovery_error is not None,
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            plan=plan,
            candidates=candidates,
            citations=citations,
            tool_trace=tuple(trace),
            warnings=(*warnings, *discovery_warning(discovery_error)),
            data_requirement=requirement,
            source_candidates=source_candidates,
            visualizations=visualizations,
        )


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
    language = name_language(question)
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

    language = name_language(question)
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
    language = response_language_for_fallback(question)

    if language == "zh":
        opening = f"在「{profile_name}」評分中，{top_name}以{top.score:.1f}/100排名第一"  # noqa: RUF001
        if runner is not None:
            runner_name = runner.entity_name or runner.entity_id
            opening += f"，高於第二名{runner_name}的{runner.score:.1f}/100"  # noqa: RUF001
        opening += f"。{inline_citations(ranking_citations)}"
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
        opening += f". {inline_citations(ranking_citations)}"
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
        opening += f". {inline_citations(ranking_citations)}"
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
            f"{item.feature_name} ({item.points:.1f} {points}) {inline_citations(item.citations)}"
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
            f"{runner_item.points:.1f} {inline_citations(citations)}"
        )
    paragraphs = [opening]
    if explanation_parts:
        paragraphs.append(f"{reason_intro} {'; '.join(explanation_parts)}.")
    if disadvantages:
        _, top_item, runner_item = disadvantages[0]
        citations = tuple(dict.fromkeys((*top_item.citations, *runner_item.citations)))
        paragraphs.append(
            f"{offset_intro} {top_item.feature_name}: {runner_item.points:.1f} {points}{versus} "
            f"{top_item.points:.1f} {inline_citations(citations)}."
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
