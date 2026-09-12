"""Structured conversation memory and deterministic follow-up resolution."""

from datetime import UTC, datetime, timedelta

from youth_compass.agent import (
    AnalysisFilters,
    AnalysisOperation,
    ConversationContext,
    ConversationContextResolver,
    DecomposedQuery,
    InMemoryConversationContextStore,
)

_SESSION_ID = "ses_0123456789abcdef0123456789abcdef"


def _previous(now: datetime) -> ConversationContext:
    return ConversationContext(
        session_id=_SESSION_ID,
        objective="compare observations",
        subject_terms=("population",),
        metric_terms=("population_count",),
        entity_ids=("banqiao", "linkou"),
        time_expression="2023-2025",
        operations=(
            AnalysisOperation.SEARCH_CATALOG,
            AnalysisOperation.INSPECT_DATASET,
            AnalysisOperation.QUERY_OBSERVATIONS,
            AnalysisOperation.COMPARE_ENTITIES,
            AnalysisOperation.EXPLAIN_LINEAGE,
        ),
        updated_at=now,
    )


def _unclear(question: str) -> DecomposedQuery:
    return DecomposedQuery(
        original_question=question,
        objective="discover relevant evidence",
        operations=(AnalysisOperation.SEARCH_CATALOG,),
        needs_clarification=True,
        clarification_question="Clarify the metric.",
    )


def test_follow_up_inherits_plan_and_narrows_entity() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, applied = ConversationContextResolver().resolve(
        "Còn Linkou thì sao?",
        _unclear("Còn Linkou thì sao?"),
        _previous(now),
    )

    assert applied is True
    assert resolved.entity_ids == ("linkou",)
    assert resolved.metric_terms == ("population_count",)
    assert resolved.time_expression == "2023-2025"
    assert resolved.operations[-2] is AnalysisOperation.COMPARE_ENTITIES
    assert resolved.needs_clarification is False


def test_follow_up_overrides_time_and_adds_age_filter() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    resolver = ConversationContextResolver()

    time_query, _ = resolver.resolve(
        "So với năm ngoái?", _unclear("So với năm ngoái?"), _previous(now)
    )
    age_query, _ = resolver.resolve(
        "Chỉ lấy nhóm 20-29 tuổi.",
        _unclear("Chỉ lấy nhóm 20-29 tuổi."),
        _previous(now),
    )

    assert time_query.time_expression == "last 2 years"
    assert age_query.filters == AnalysisFilters(age_lower=20, age_upper=29)


def test_pronoun_follow_up_changes_only_time_without_matching_district_codes_in_years() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    previous = _previous(now).model_copy(update={"entity_ids": ("01", "02", "03", "04", "05")})
    question = "So how about it from 2019 to 2020"
    current = _unclear(question).model_copy(update={"time_expression": "2019-2020"})

    resolved, applied = ConversationContextResolver().resolve(question, current, previous)

    assert applied is True
    assert resolved.metric_terms == ("population_count",)
    assert resolved.entity_ids == previous.entity_ids
    assert resolved.time_expression == "2019-2020"
    assert resolved.needs_clarification is False


def test_deictic_district_keeps_entity_instead_of_treating_trend_as_a_place() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    previous = _previous(now).model_copy(update={"entity_ids": ("wugu",)})
    question = "Show how about the trend from 2024 to 2025 in that district"
    current = _unclear(question).model_copy(update={"time_expression": "2024-2025"})

    resolved, applied = ConversationContextResolver().resolve(question, current, previous)

    assert applied is True
    assert resolved.metric_terms == ("population_count",)
    assert resolved.entity_ids == ("wugu",)
    assert resolved.time_expression == "2024-2025"
    assert resolved.needs_clarification is False


def test_store_expires_context_and_retains_only_structured_fields() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    current = now
    store = InMemoryConversationContextStore(ttl=timedelta(minutes=5), clock=lambda: current)
    context = _previous(now)

    store.put(context)

    assert store.get(_SESSION_ID) == context
    assert not ({"question", "answer", "reasoning", "messages"} & context.model_dump().keys())
    current = now + timedelta(minutes=6)
    assert store.get(_SESSION_ID) is None


def test_self_contained_question_does_not_inherit_previous_scope() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    fresh = DecomposedQuery(
        original_question="Compare unemployment in Tamsui from 2020 to 2024",
        objective="compare unemployment",
        subject_terms=("unemployment",),
        metric_terms=("unemployment_rate",),
        entity_ids=("tamsui",),
        time_expression="2020-2024",
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )

    resolved, applied = ConversationContextResolver().resolve(
        fresh.original_question, fresh, _previous(now)
    )

    assert applied is False
    assert resolved == fresh


def test_age_filter_is_parsed_without_any_previous_turn() -> None:
    # An escaped EN DASH: users paste it from reports, and it must still parse.
    question = "Population for the 20\u201329 group in Banqiao"
    current = DecomposedQuery(
        original_question=question,
        objective="retrieve population",
        entity_ids=("banqiao",),
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )

    resolved, applied = ConversationContextResolver().resolve(question, current, None)

    assert applied is False
    assert resolved.filters == AnalysisFilters(age_lower=20, age_upper=29)


def test_store_evicts_the_oldest_session_past_its_bound() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    store = InMemoryConversationContextStore(max_sessions=1, clock=lambda: now)
    oldest = _previous(now)
    newest = _previous(now + timedelta(minutes=1)).model_copy(
        update={"session_id": "ses_ffffffffffffffffffffffffffffffff"}
    )

    store.put(oldest)
    store.put(newest)

    assert store.get(oldest.session_id) is None
    assert store.get(newest.session_id) == newest


def test_unlisted_phrasing_still_inherits_when_the_turn_would_dead_end() -> None:
    """A follow-up with no keyword marker must not lose the session."""
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, applied = ConversationContextResolver().resolve(
        "Linkou?", _unclear("Linkou?"), _previous(now)
    )

    assert applied is True
    assert resolved.entity_ids == ("linkou",)
    assert resolved.metric_terms == ("population_count",)
    assert resolved.needs_clarification is False


def test_bare_metric_word_is_not_mistaken_for_an_entity() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    named_metric = DecomposedQuery(
        original_question="unemployment?",
        objective="analyze a time trend",
        metric_terms=("unemployment_count",),
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )

    resolved, _ = ConversationContextResolver().resolve(
        "unemployment?", named_metric, _previous(now)
    )

    assert resolved.metric_terms == ("unemployment_count",)
    assert resolved.entity_ids == ("banqiao", "linkou")


def test_gender_follow_up_adds_only_the_gender_filter() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, applied = ConversationContextResolver().resolve(
        "Chỉ nữ giới.", _unclear("Chỉ nữ giới."), _previous(now)
    )

    assert applied is True
    assert resolved.filters == AnalysisFilters(gender_code="female")
    assert resolved.entity_ids == ("banqiao", "linkou")


def test_naming_both_genders_applies_no_gender_filter() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, _ = ConversationContextResolver().resolve(
        "Compare male and female only.",
        _unclear("Compare male and female only."),
        _previous(now),
    )

    assert resolved.filters.gender_code is None


def test_a_new_age_range_replaces_the_inherited_one() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    previous = _previous(now).model_copy(
        update={"filters": AnalysisFilters(age_lower=20, age_upper=29)}
    )

    resolved, _ = ConversationContextResolver().resolve(
        "Chỉ nhóm 30-39 tuổi.", _unclear("Chỉ nhóm 30-39 tuổi."), previous
    )

    assert resolved.filters == AnalysisFilters(age_lower=30, age_upper=39)


def test_a_one_sided_bound_replaces_the_whole_inherited_range() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    previous = _previous(now).model_copy(
        update={"filters": AnalysisFilters(age_lower=20, age_upper=29)}
    )

    resolved, _ = ConversationContextResolver().resolve(
        "Only ages under 25.", _unclear("Only ages under 25."), previous
    )

    # A stale lower bound of 20 would silently contradict "under 25".
    assert resolved.filters == AnalysisFilters(age_lower=None, age_upper=25)


def test_a_year_range_is_never_read_as_an_age_bound() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    fresh = DecomposedQuery(
        original_question="Compare unemployment in Tamsui from 2020 to 2024",
        objective="compare unemployment",
        metric_terms=("unemployment_count",),
        entity_ids=("tamsui",),
        time_expression="2020-2024",
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )

    resolved, applied = ConversationContextResolver().resolve(
        fresh.original_question, fresh, _previous(now)
    )

    assert applied is False
    assert resolved.filters == AnalysisFilters()


def test_a_broad_new_request_does_not_inherit_a_narrow_entity_scope() -> None:
    """Length alone must not turn a wide question into a refinement."""
    now = datetime(2026, 9, 12, tzinfo=UTC)
    broad = DecomposedQuery(
        original_question="Compare youth unemployment across every district in New Taipei",
        objective="compare observations",
        metric_terms=("unemployment_count",),
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )

    resolved, applied = ConversationContextResolver().resolve(
        broad.original_question, broad, _previous(now)
    )

    assert applied is False
    assert resolved.entity_ids == ()


def test_a_multi_word_place_name_resolves_to_its_canonical_code() -> None:
    """Capturing one ASCII word truncated "Lâm Khẩu" and invented an entity."""
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, _ = ConversationContextResolver().resolve(
        "Còn Lâm Khẩu thì sao?", _unclear("Còn Lâm Khẩu thì sao?"), _previous(now)
    )

    assert resolved.entity_ids == ("17",)


def test_an_unknown_place_is_reported_verbatim_not_truncated() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)

    resolved, _ = ConversationContextResolver().resolve(
        "Còn Tam Trọng thì sao?", _unclear("Còn Tam Trọng thì sao?"), _previous(now)
    )

    # The ontology does not know this name, so the downstream failure must name
    # the whole phrase the user typed rather than a fragment of it.
    assert resolved.entity_ids == ("tam trọng",)


def test_a_refinement_phrase_is_never_mistaken_for_a_bare_place_name() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    resolver = ConversationContextResolver()

    for question in ("So với năm ngoái?", "Chỉ nữ giới.", "Chỉ lấy nhóm 20-24 tuổi."):
        resolved, _ = resolver.resolve(question, _unclear(question), _previous(now))
        assert resolved.entity_ids == ("banqiao", "linkou"), question
