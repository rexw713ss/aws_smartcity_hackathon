"""Grounded narrative composition and deterministic safety fallback."""

import asyncio
import json

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


class StreamingModelProvider(StaticModelProvider):
    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        for part in ("Banqiao tăng từ ", "100 lên 120 (20%) ", "[data-1]."):
            yield part


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
    prompt = json.loads(provider.requests[0].prompt)
    assert prompt["safe_answer_template"] == _context().fallback_answer
    assert set(prompt["allowed_number_strings"]) == {"100", "120", "20", "+20"}
    assert prompt["response_language"] == "Vietnamese"
    assert "Do not calculate differences" in provider.requests[0].system


def test_model_composer_requests_taiwan_traditional_chinese() -> None:
    provider = StaticModelProvider(
        '{"answer":"板橋人口從100增加到120（20%）[data-1]。","citation_ids":["data-1"]}'  # noqa: RUF001
    )
    context = _context().model_copy(update={"question": "板橋的人口變化如何？"})  # noqa: RUF001

    result = asyncio.run(ModelAnswerComposer(provider).compose(context))

    assert result.mode == "model"
    assert "Taiwan Traditional Chinese" in provider.requests[0].system
    assert json.loads(provider.requests[0].prompt)["response_language"] == (
        "Taiwan Traditional Chinese (zh-TW)"
    )


def test_model_composer_marks_ascii_questions_as_english() -> None:
    provider = StaticModelProvider(
        '{"answer":"Banqiao increased from 100 to 120 (20%) [data-1].","citation_ids":["data-1"]}'
    )
    context = _context().model_copy(update={"question": "How did the population change?"})

    result = asyncio.run(ModelAnswerComposer(provider).compose(context))

    assert result.mode == "model"
    assert json.loads(provider.requests[0].prompt)["response_language"] == "English"


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


def test_model_composer_forwards_bedrock_stream_snapshots() -> None:
    snapshots: list[str] = []

    # Use an async callback at the boundary, as the API does.
    async def collect() -> object:
        async def receive(text: str) -> None:
            snapshots.append(text)

        return await ModelAnswerComposer(StreamingModelProvider("unused")).compose(
            _context(), receive
        )

    result = asyncio.run(collect())
    assert snapshots == [
        "Banqiao tăng từ ",
        "Banqiao tăng từ 100 lên 120 (20%) ",
        "Banqiao tăng từ 100 lên 120 (20%) [data-1].",
    ]
    assert result.mode == "model"  # type: ignore[attr-defined]
