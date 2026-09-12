"""Grounded narrative composition and deterministic safety fallback."""

import asyncio

import pytest

from youth_compass.agent import (
    AnswerCompositionContext,
    DeterministicAnswerComposer,
    FallbackAnswerComposer,
    ModelAnswerComposer,
)
from youth_compass.domain import ModelInvocationError
from youth_compass.ports import ModelRequest, ModelResponse


class StaticModelProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=self.text, model_id="bedrock-test")


def _context() -> AnswerCompositionContext:
    return AnswerCompositionContext(
        question="Dân số thay đổi thế nào?",
        analysis_type="observation_comparison",
        grounded_facts_json=('{"entity":"Banqiao","first":100,"last":120,"percent_change":20}'),
        allowed_citation_ids=("data-1",),
        fallback_answer="Banqiao increased from 100 to 120 (+20%) [data-1].",
    )


def test_model_composer_accepts_only_grounded_numbers_and_citations() -> None:
    provider = StaticModelProvider(
        '{"answer":"Banqiao tăng từ 100 lên 120, tương đương 20% [data-1].",'
        '"citation_ids":["data-1"]}'
    )

    result = asyncio.run(ModelAnswerComposer(provider).compose(_context()))

    assert result.mode == "model"
    assert result.citation_ids == ("data-1",)
    assert "20%" in result.answer
    assert provider.requests[0].temperature == 0
    assert provider.requests[0].response_schema is not None


def test_model_composer_requests_taiwan_traditional_chinese() -> None:
    provider = StaticModelProvider(
        '{"answer":"板橋人口從100增加到120（20%）[data-1]。","citation_ids":["data-1"]}'  # noqa: RUF001
    )
    context = _context().model_copy(update={"question": "板橋的人口變化如何？"})  # noqa: RUF001

    result = asyncio.run(ModelAnswerComposer(provider).compose(context))

    assert result.mode == "model"
    assert "Taiwan Traditional Chinese" in provider.requests[0].system


@pytest.mark.parametrize(
    "draft, message",
    (
        (
            '{"answer":"Banqiao will reach 999 next year.","citation_ids":[]}',
            "invented numerical values",
        ),
        (
            '{"answer":"Supported by [data-9].","citation_ids":["data-9"]}',
            "invented a citation",
        ),
        (
            '{"answer":"Supported by [data-9].","citation_ids":[]}',
            "unknown citation",
        ),
    ),
)
def test_model_composer_rejects_ungrounded_claims(draft: str, message: str) -> None:
    with pytest.raises(ModelInvocationError, match=message):
        asyncio.run(ModelAnswerComposer(StaticModelProvider(draft)).compose(_context()))


def test_answer_composer_falls_back_to_verified_template() -> None:
    composer = FallbackAnswerComposer(
        ModelAnswerComposer(
            StaticModelProvider('{"answer":"Banqiao will reach 999 next year.","citation_ids":[]}')
        ),
        DeterministicAnswerComposer(),
    )

    result = asyncio.run(composer.compose(_context()))

    assert result.mode == "deterministic"
    assert result.answer == _context().fallback_answer
