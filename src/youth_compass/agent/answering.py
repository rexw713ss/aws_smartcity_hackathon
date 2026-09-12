"""Grounded answer composition with citation and numerical safety checks."""

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Protocol

from pydantic import ValidationError

from youth_compass.agent.contracts import (
    AnswerCompositionContext,
    AnswerDraft,
    ComposedAnswer,
)
from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ontology import NameLanguage, question_language
from youth_compass.ports import ModelProvider, ModelRequest

_LOGGER = logging.getLogger(__name__)

_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?")
_CITATION = re.compile(r"\bdata-\d+\b")


class AnswerComposer(Protocol):
    """Convert grounded public facts into a user-facing narrative."""

    async def compose(self, context: AnswerCompositionContext) -> ComposedAnswer:
        """Return a narrative without changing the structured source of truth."""
        ...


class DeterministicAnswerComposer:
    """Return the application's verified template when no model is configured."""

    async def compose(self, context: AnswerCompositionContext) -> ComposedAnswer:
        return ComposedAnswer(
            answer=context.fallback_answer,
            citation_ids=context.allowed_citation_ids,
            mode="deterministic",
        )


class ModelAnswerComposer:
    """Ask a model to verbalize facts, then reject invented citations or numbers."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def compose(self, context: AnswerCompositionContext) -> ComposedAnswer:
        try:
            grounded_facts = json.loads(context.grounded_facts_json)
        except json.JSONDecodeError as exc:
            raise ModelInvocationError("answer context contains invalid grounded JSON") from exc
        numeric_source = _without_citations(
            context.grounded_facts_json + " " + context.fallback_answer,
            context.allowed_citation_ids,
        )
        response = await self._provider.generate(
            ModelRequest(
                system=(
                    "Write a concise, natural answer in RESPONSE_LANGUAGE; that field is "
                    "authoritative. Answer the user's actual question directly instead of exposing "
                    "an analysis template. For an observation comparison, lead with the clearest "
                    "trend in one conversational sentence, including the place, period, start and "
                    "end values, and change. For a decision ranking, start with the "
                    "recommendation, "
                    "then compare the winner with the runner-up using their feature contributions "
                    "when both are available. Put the relevant "
                    "citation ID immediately after every evidence-based claim. The answer must be "
                    "understandable without looking at a chart or table; visualizations are only "
                    "supporting material. Avoid mechanical headings, record counts, and redundant "
                    "source boilerplate. Use short paragraphs; only use bullets when comparing "
                    "three or more entities. "
                    "Do not return HTML, Markdown headings, or Markdown tables. "
                    "When it is Taiwan Traditional Chinese, never convert it to Simplified "
                    "Chinese. "
                    "Use only GROUNDED_FACTS. Do not add facts, entities, numbers, causal "
                    "claims, or citation IDs. Do not calculate differences, percentages, or "
                    "rounded values. Name every place by its entity_name and never print an "
                    "internal identifier such as entity_id, feature_code, or metric_code. "
                    "Every number in the answer must be copied character-for-"
                    "character from ALLOWED_NUMBER_STRINGS. Use SAFE_ANSWER_TEMPLATE as the "
                    "semantic outline and preserve its limitations. Return only JSON matching "
                    "the provided schema."
                ),
                prompt=json.dumps(
                    {
                        "question": context.question,
                        "response_language": _response_language(context.question),
                        "analysis_type": context.analysis_type,
                        "grounded_facts": grounded_facts,
                        "allowed_citation_ids": context.allowed_citation_ids,
                        "allowed_number_strings": sorted(set(_NUMBER.findall(numeric_source))),
                        "safe_answer_template": context.fallback_answer,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                max_tokens=1500,
                temperature=0,
                response_schema=AnswerDraft.model_json_schema(),
            )
        )
        try:
            draft = AnswerDraft.model_validate_json(response.text)
        except ValidationError as exc:
            raise ModelInvocationError("model returned an invalid answer draft") from exc
        allowed_citations = set(context.allowed_citation_ids)
        if not set(draft.citation_ids).issubset(allowed_citations):
            raise ModelInvocationError("model answer invented a citation")
        if not set(_CITATION.findall(draft.answer)).issubset(allowed_citations):
            raise ModelInvocationError("model answer referenced an unknown citation")
        scrubbed_answer = draft.answer
        for citation_id in allowed_citations:
            scrubbed_answer = scrubbed_answer.replace(citation_id, "")
        allowed_numbers = _numbers(numeric_source)
        invented_numbers = _numbers(scrubbed_answer) - allowed_numbers
        if invented_numbers:
            rendered = ", ".join(sorted(str(item) for item in invented_numbers))
            raise ModelInvocationError(f"model answer invented numerical values: {rendered}")
        return ComposedAnswer(
            answer=draft.answer,
            citation_ids=draft.citation_ids,
            mode="model",
        )


class FallbackAnswerComposer:
    """Fall back to a deterministic template on any model-boundary failure."""

    def __init__(self, primary: AnswerComposer, fallback: AnswerComposer) -> None:
        self._primary = primary
        self._fallback = fallback

    async def compose(self, context: AnswerCompositionContext) -> ComposedAnswer:
        try:
            return await self._primary.compose(context)
        except ModelInvocationError as exc:
            # A silent fallback is the worst failure mode here: answers stay
            # correct and grounded, so a misconfigured model provider looks
            # exactly like a working one. The response trace still reports
            # mode='deterministic'; this makes it visible in the logs too.
            _LOGGER.warning("answer composer fell back to the deterministic template: %s", exc)
            return await self._fallback.compose(context)


def _numbers(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for token in _NUMBER.findall(text):
        try:
            values.add(Decimal(token).normalize())
        except InvalidOperation:
            continue
    return values


def _without_citations(text: str, citation_ids: tuple[str, ...]) -> str:
    for citation_id in citation_ids:
        text = text.replace(citation_id, "")
    return text


def _response_language(question: str) -> str:
    language = question_language(question)
    if language is NameLanguage.ZH_HANT:
        return "Taiwan Traditional Chinese (zh-TW)"
    if language is NameLanguage.ENGLISH:
        return "English"
    return "Vietnamese"
