"""Bounded structured conversation context for follow-up query resolution."""

import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from youth_compass.agent.contracts import (
    AnalysisFilters,
    ConversationContext,
    DecomposedQuery,
    GenderCode,
)
from youth_compass.ontology import resolve_district_name

# An explicit marker is a positive signal, never the only one: follow-up
# detection also succeeds structurally, so an unlisted phrasing degrades to the
# structural rules below rather than losing the session.
_FOLLOW_UP = re.compile(
    r"\b(?:what about|how about|compared with|compared to|only|just|instead|"
    r"còn|thì sao|so với|chỉ|riêng|năm ngoái)\b|(?:那|至於|只|去年|呢|如何)",
    re.IGNORECASE,
)
# The escaped range \u2010-\u2015 covers every dash users type between ages,
# without pasting look-alike characters into this file.
_AGE_RANGE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:[-\u2010-\u2015]|to|đến|到|至)\s*(\d{1,2})(?!\d)",
    re.IGNORECASE,
)
# A one-sided bound needs an explicit age cue. Without it "from 2020 to 2024"
# and "under 30 districts" would both be read as age bounds.
_AGE_CUE = re.compile(
    r"\b(?:age|ages|aged|years? old|tuổi|nhóm tuổi|độ tuổi)\b|歲|年齡", re.IGNORECASE
)
_AGE_PLUS = re.compile(r"(?<!\d)(\d{1,2})\s*\+")
_AGE_LOWER_ONLY = re.compile(r"(?:from|over|above|trên|từ)\s+(?<!\d)(\d{1,2})(?!\d)", re.IGNORECASE)
_AGE_UPPER_ONLY = re.compile(
    r"(?:under|below|up to|dưới|tới)\s+(?<!\d)(\d{1,2})(?!\d)", re.IGNORECASE
)
_LAST_YEAR = re.compile(r"\b(?:last|previous)\s+year\b|\bnăm ngoái\b|去年", re.IGNORECASE)
# "nam" alone collides with place names, so the masculine forms require their
# qualifier. "nữ" and the CJK forms are unambiguous on their own.
_GENDERS: tuple[tuple[GenderCode, re.Pattern[str]], ...] = (
    (
        "female",
        re.compile(r"\b(?:female|women|woman|nữ|phụ nữ)\b|女性|女生|婦女", re.IGNORECASE),
    ),
    (
        "male",
        re.compile(
            r"\b(?:male|men|man|nam giới|phái nam|giới tính nam)\b|男性|男生",
            re.IGNORECASE,
        ),
    ),
)
# A place name can carry several words and diacritics ("Tam Trọng", "New
# Taipei"), so the capture is greedy across letters and spaces and is trimmed
# afterwards. Capturing a single ASCII word truncated "Tam Trọng" to "tam" and
# sent a meaningless identifier downstream.
_NAME = r"([^\W\d_][^\W\d_ ]*(?:[ ][^\W\d_][^\W\d_ ]*){0,3})"
_NEW_ENTITY = (
    re.compile(r"\b(?:what|how)\s+about\s+" + _NAME, re.IGNORECASE),
    re.compile(r"\b(?:còn|riêng|tại|ở)\s+" + _NAME, re.IGNORECASE),
)
# Deictic geography refers back to the previous entity scope. Check it before
# the broad ``how about X`` capture; otherwise a phrase such as "how about the
# trend ... in that district" is misread as a request for a district named
# ``trend``.
_SAME_ENTITY = re.compile(
    r"\b(?:that|this|the same)\s+(?:district|area|place|location)\b"
    r"|\b(?:quận|huyện|khu vực|địa điểm)\s+(?:đó|này|cũ)\b"
    r"|(?:該|這個|那個|同一)(?:區|地區|地點)",
    re.IGNORECASE,
)
# Words that follow the marker but are never part of a place name.
_NAME_STOPWORDS = frozenset(
    {
        "thì",
        "sao",
        "về",
        "cho",
        "của",
        "the",
        "in",
        "for",
        "from",
        "about",
        "it",
        "this",
        "that",
        "them",
        "nữa",
        "này",
        "đó",
    }
)
# A bare name, optionally with a question mark, is a common follow-up ("Linkou?").
# Only consulted once the turn is already known to be a follow-up and the
# decomposer recognized no metric in it, because a bare metric word looks
# identical to a bare place name.
_BARE_ENTITY = re.compile(r"^\s*" + _NAME + r"\s*\??\s*$", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# A refinement carries a handful of words at most ("unemployment?", "chỉ nữ
# giới", "so với năm ngoái"). Anything longer is treated as a new question, so a
# broad request such as "across every district" cannot inherit a narrow scope.
_MAX_REFINEMENT_WORDS = 5


class ConversationContextStore(Protocol):
    """Minimal replaceable persistence boundary for structured session state."""

    def get(self, session_id: str) -> ConversationContext | None:
        """Return a live context, or None when it is absent or expired."""
        ...

    def put(self, context: ConversationContext) -> None:
        """Store the newest immutable context revision."""
        ...


class InMemoryConversationContextStore:
    """Thread-safe bounded process-local store; a durable adapter can replace it."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=30),
        max_sessions: int = 1_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("conversation context TTL must be positive")
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._contexts: dict[str, ConversationContext] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> ConversationContext | None:
        now = self._clock()
        with self._lock:
            context = self._contexts.get(session_id)
            if context is not None and now - context.updated_at > self._ttl:
                del self._contexts[session_id]
                return None
            return context

    def put(self, context: ConversationContext) -> None:
        with self._lock:
            current = self._contexts.get(context.session_id)
            if current is not None and current.revision >= context.revision:
                return
            self._contexts[context.session_id] = context
            if len(self._contexts) > self._max_sessions:
                oldest = min(self._contexts.values(), key=lambda item: item.updated_at)
                del self._contexts[oldest.session_id]


class ConversationContextResolver:
    """Fill only omitted follow-up fields from the previous structured turn."""

    def resolve(
        self,
        question: str,
        current: DecomposedQuery,
        previous: ConversationContext | None,
    ) -> tuple[DecomposedQuery, bool]:
        parsed_filters = _filters(question)
        if previous is None or not _is_follow_up(question, current, previous):
            if parsed_filters == current.filters:
                return current, False
            return current.model_copy(update={"filters": parsed_filters}), False

        entities = current.entity_ids or _entities_from_follow_up(
            question, previous.entity_ids, allow_bare=not current.metric_terms
        )
        if not entities:
            entities = previous.entity_ids
        filters = _merge_filters(parsed_filters, previous.filters)
        inherited_plan = current.needs_clarification
        resolved = current.model_copy(
            update={
                "objective": previous.objective if inherited_plan else current.objective,
                "subject_terms": current.subject_terms or previous.subject_terms,
                "metric_terms": current.metric_terms or previous.metric_terms,
                "entity_ids": entities,
                "time_expression": (
                    _time_expression(question)
                    or current.time_expression
                    or previous.time_expression
                ),
                "filters": filters,
                "operations": previous.operations if inherited_plan else current.operations,
                "needs_clarification": False if inherited_plan else current.needs_clarification,
                "clarification_question": (
                    None if inherited_plan else current.clarification_question
                ),
            }
        )
        return resolved, resolved != current


def new_session_id() -> str:
    """Return an opaque high-entropy identifier safe for the public API contract."""

    return f"ses_{uuid.uuid4().hex}"


def context_from_decomposition(
    session_id: str,
    decomposition: DecomposedQuery,
    updated_at: datetime,
    previous: ConversationContext | None,
) -> ConversationContext:
    """Project a decomposition into the only fields session memory may retain."""

    if previous is not None:
        return previous.next(decomposition, updated_at)
    return ConversationContext(
        session_id=session_id,
        objective=decomposition.objective,
        subject_terms=decomposition.subject_terms,
        metric_terms=decomposition.metric_terms,
        entity_ids=decomposition.entity_ids,
        time_expression=decomposition.time_expression,
        filters=decomposition.filters,
        operations=decomposition.operations,
        updated_at=updated_at,
    )


def _is_follow_up(question: str, current: DecomposedQuery, previous: ConversationContext) -> bool:
    """Decide whether a live session may supply the fields this question omits.

    Three independent signals, so an unlisted phrasing is not a dead end:

    1. An explicit marker such as "what about" or "còn ... thì sao".
    2. The decomposition would otherwise dead-end in a clarification request.
       Inheriting a known scope is strictly better than answering nothing.
    3. The question is a very short refinement that changes one axis and leaves
       the others unstated. A question that states its own metric, entity, and
       period is self-contained and inherits nothing, however short it is.
    """

    if _FOLLOW_UP.search(question):
        return True
    if current.needs_clarification:
        return True
    if len(_WORD.findall(question)) > _MAX_REFINEMENT_WORDS:
        return False
    stated = (
        bool(current.metric_terms),
        bool(current.entity_ids),
        current.time_expression is not None,
    )
    if all(stated):
        return False
    return (
        any(stated)
        or not _filters(question).is_empty
        or _time_expression(question) is not None
        or bool(_entities_from_follow_up(question, previous.entity_ids, allow_bare=False))
    )


def _merge_filters(parsed: AnalysisFilters, previous: AnalysisFilters) -> AnalysisFilters:
    """Let the new question override a filter and inherit the ones it omits.

    An age bound is inherited per side, so "under 30" after "20 to 29" keeps no
    stale lower bound it would contradict: a question that names one side of a
    range replaces the whole range.
    """

    age_named = parsed.age_lower is not None or parsed.age_upper is not None
    return AnalysisFilters(
        age_lower=parsed.age_lower if age_named else previous.age_lower,
        age_upper=parsed.age_upper if age_named else previous.age_upper,
        gender_code=parsed.gender_code or previous.gender_code,
    )


def _filters(question: str) -> AnalysisFilters:
    lower, upper = _age_bounds(question)
    return AnalysisFilters(age_lower=lower, age_upper=upper, gender_code=_gender(question))


def _age_bounds(question: str) -> tuple[int | None, int | None]:
    if match := _AGE_RANGE.search(question):
        lower, upper = sorted((int(match.group(1)), int(match.group(2))))
        return lower, upper
    if match := _AGE_PLUS.search(question):
        return int(match.group(1)), None
    if not _AGE_CUE.search(question):
        return None, None
    if match := _AGE_UPPER_ONLY.search(question):
        return None, int(match.group(1))
    if match := _AGE_LOWER_ONLY.search(question):
        return int(match.group(1)), None
    return None, None


def _gender(question: str) -> GenderCode | None:
    matched = [code for code, pattern in _GENDERS if pattern.search(question)]
    # Naming both genders is a request for the whole population, not a filter.
    return matched[0] if len(matched) == 1 else None


def _time_expression(question: str) -> str | None:
    if _LAST_YEAR.search(question):
        # A comparison needs the latest observation and its predecessor.
        return "last 2 years"
    return None


def _entities_from_follow_up(
    question: str, previous: tuple[str, ...], *, allow_bare: bool
) -> tuple[str, ...]:
    normalized = question.casefold()
    if _SAME_ENTITY.search(question):
        return previous
    # Canonical district codes can be numeric (for example ``01``). A plain
    # substring check mistakes those codes for pieces of years such as 2019 or
    # 2020 and silently narrows a time-only follow-up to the wrong districts.
    mentioned = tuple(
        entity
        for entity in previous
        if re.search(rf"(?<!\w){re.escape(entity.casefold())}(?!\w)", normalized)
    )
    if mentioned:
        return mentioned
    for pattern in _NEW_ENTITY:
        match = pattern.search(question)
        # An explicit "còn X" names X even when the ontology does not know it,
        # so a failure can report the place the user actually asked about.
        if match is not None and (named := _place_name(match.group(1), require_known=False)):
            return (named,)
    bare = _BARE_ENTITY.search(question) if allow_bare else None
    # A bare phrase carries no marker saying it is a place, and questions like
    # "So với năm ngoái?" have the same shape, so only a recognized name counts.
    if bare is not None and (named := _place_name(bare.group(1), require_known=True)):
        return (named,)
    return ()


def _place_name(captured: str, *, require_known: bool) -> str | None:
    """Trim a captured phrase to a usable identifier, resolving known districts.

    A name the ontology recognizes becomes its canonical district code, so the
    observation query matches rows regardless of the language it was typed in.
    With ``require_known`` the phrase is otherwise rejected; without it the
    trimmed phrase is kept verbatim rather than guessed at, so a failure names
    what was actually asked for instead of a truncated fragment.
    """

    words = [word for word in captured.split() if word.casefold() not in _NAME_STOPWORDS]
    candidate = words
    while candidate:
        if (district := resolve_district_name(" ".join(candidate)).district) is not None:
            return district.code
        # The marker may be followed by trailing words that belong to the
        # question rather than the name, so shrink from the right.
        candidate = candidate[:-1]
    if require_known:
        return None
    return " ".join(words).casefold() or None
