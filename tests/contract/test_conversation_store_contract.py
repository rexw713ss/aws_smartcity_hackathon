"""ConversationContextStore contract.

Every binding must agree on round-trip, absence, revision ordering, and the
promise that only structured scope is retained. The in-memory store and the
durable DynamoDB store therefore cannot drift: a follow-up answered on a
multi-instance deployment inherits exactly what it inherits locally.
"""

from datetime import UTC, datetime

from youth_compass.agent import (
    AnalysisFilters,
    AnalysisOperation,
    ConversationContext,
    ConversationContextStore,
)

_SESSION_ID = "ses_0123456789abcdef0123456789abcdef"
_OTHER_SESSION_ID = "ses_fedcba9876543210fedcba9876543210"
# A live clock, because every binding expires an idle session by wall time: a
# fixed past timestamp would be legitimately expired before the first read.
_NOW = datetime.now(UTC)
# No transcript, prompt, answer, or reasoning field may ever appear here.
_FORBIDDEN_FIELDS = {"question", "answer", "reasoning", "messages", "transcript", "prompt"}


def _context(
    session_id: str = _SESSION_ID,
    *,
    revision: int = 1,
    entity_ids: tuple[str, ...] = ("banqiao", "linkou"),
) -> ConversationContext:
    return ConversationContext(
        session_id=session_id,
        revision=revision,
        objective="compare observations",
        subject_terms=("population",),
        metric_terms=("population_count",),
        entity_ids=entity_ids,
        time_expression="2023-2025",
        filters=AnalysisFilters(age_lower=20, age_upper=29, gender_code="female"),
        operations=(
            AnalysisOperation.SEARCH_CATALOG,
            AnalysisOperation.INSPECT_DATASET,
            AnalysisOperation.QUERY_OBSERVATIONS,
            AnalysisOperation.COMPARE_ENTITIES,
            AnalysisOperation.EXPLAIN_LINEAGE,
        ),
        updated_at=_NOW,
    )


class TestConversationStoreContract:
    def test_put_then_get_round_trips_every_structured_field(
        self, conversation_store: ConversationContextStore
    ) -> None:
        context = _context()
        conversation_store.put(context)
        assert conversation_store.get(_SESSION_ID) == context

    def test_get_of_unknown_session_returns_none(
        self, conversation_store: ConversationContextStore
    ) -> None:
        assert conversation_store.get(_OTHER_SESSION_ID) is None

    def test_a_newer_revision_replaces_the_stored_context(
        self, conversation_store: ConversationContextStore
    ) -> None:
        conversation_store.put(_context(revision=1))
        conversation_store.put(_context(revision=2, entity_ids=("tamsui",)))
        stored = conversation_store.get(_SESSION_ID)
        assert stored is not None
        assert stored.revision == 2
        assert stored.entity_ids == ("tamsui",)

    def test_an_out_of_order_revision_is_discarded(
        self, conversation_store: ConversationContextStore
    ) -> None:
        conversation_store.put(_context(revision=3, entity_ids=("tamsui",)))
        conversation_store.put(_context(revision=2, entity_ids=("banqiao",)))
        stored = conversation_store.get(_SESSION_ID)
        assert stored is not None
        assert stored.revision == 3
        assert stored.entity_ids == ("tamsui",)

    def test_sessions_are_isolated_from_each_other(
        self, conversation_store: ConversationContextStore
    ) -> None:
        conversation_store.put(_context(entity_ids=("banqiao",)))
        conversation_store.put(_context(_OTHER_SESSION_ID, entity_ids=("tamsui",)))
        first = conversation_store.get(_SESSION_ID)
        second = conversation_store.get(_OTHER_SESSION_ID)
        assert first is not None and first.entity_ids == ("banqiao",)
        assert second is not None and second.entity_ids == ("tamsui",)

    def test_stored_context_retains_no_conversational_text(
        self, conversation_store: ConversationContextStore
    ) -> None:
        conversation_store.put(_context())
        stored = conversation_store.get(_SESSION_ID)
        assert stored is not None
        assert not (_FORBIDDEN_FIELDS & stored.model_dump().keys())
