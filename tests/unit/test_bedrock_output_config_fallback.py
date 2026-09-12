"""Structured output must work on models that reject Converse's outputConfig.

Regression coverage for a live failure: with the copilot pointed at Claude
Sonnet, every Bedrock call returned

    ValidationException: This model doesn't support the outputConfig field.

so the answer composer silently fell back to a deterministic template and no
generative AI ran at all. Amazon Nova accepts the field; Anthropic models reject
it. The adapter has to serve both.
"""

import asyncio

import botocore.exceptions
import pytest

from adapters.aws.bedrock_model import BedrockModelProvider
from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ports import ModelRequest

SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"winner": {"type": "string"}},
    "required": ["winner"],
    "additionalProperties": False,
}

_OUTPUT_CONFIG_REJECTION = {
    "Error": {
        "Code": "ValidationException",
        "Message": (
            "This model doesn't support the outputConfig field. Remove outputConfig and try again."
        ),
    }
}


def _reply(text: str) -> dict[str, object]:
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": 11, "outputTokens": 5},
        "stopReason": "end_turn",
    }


class _RejectsOutputConfig:
    """A model that refuses outputConfig, as Anthropic models do."""

    def __init__(self, text: str = '{"winner": "banqiao"}') -> None:
        self.calls: list[dict[str, object]] = []
        self._text = text

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if "outputConfig" in kwargs:
            raise botocore.exceptions.ClientError(_OUTPUT_CONFIG_REJECTION, "Converse")
        return _reply(self._text)


class _AcceptsOutputConfig:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return _reply('{"winner": "linkou"}')


def _generate(client: object, **overrides: object) -> object:
    provider = BedrockModelProvider("test-model", client=client)  # type: ignore[arg-type]
    request = ModelRequest(prompt="who wins?", response_schema=SCHEMA, **overrides)  # type: ignore[arg-type]
    return asyncio.run(provider.generate(request))


class TestOutputConfigFallback:
    def test_retries_without_output_config_and_still_returns_the_payload(self) -> None:
        client = _RejectsOutputConfig()

        response = _generate(client)

        assert response.text == '{"winner": "banqiao"}'  # type: ignore[attr-defined]
        assert len(client.calls) == 2, "expected one rejected call then one retry"
        assert "outputConfig" in client.calls[0]
        assert "outputConfig" not in client.calls[1]

    def test_the_fallback_states_the_schema_in_the_prompt(self) -> None:
        # Without the API constraining output, the contract has to be in the
        # prompt or the model has no reason to emit JSON.
        client = _RejectsOutputConfig()

        _generate(client)

        system_text = " ".join(
            str(block.get("text", ""))
            for block in client.calls[1]["system"]  # type: ignore[union-attr]
        )
        assert "JSON Schema" in system_text
        assert "winner" in system_text

    def test_the_rejected_call_happens_only_once(self) -> None:
        # The capability is remembered, so a chatty session does not pay for a
        # doomed call on every request.
        client = _RejectsOutputConfig()
        provider = BedrockModelProvider("test-model", client=client)  # type: ignore[arg-type]
        request = ModelRequest(prompt="who wins?", response_schema=SCHEMA)

        asyncio.run(provider.generate(request))
        asyncio.run(provider.generate(request))

        with_config = [call for call in client.calls if "outputConfig" in call]
        assert len(with_config) == 1, "outputConfig was re-sent after being rejected"

    def test_a_fenced_reply_is_still_parsed(self) -> None:
        # Models told to emit bare JSON wrap it in a fence often enough that
        # trusting the raw text would make this path flaky.
        client = _RejectsOutputConfig('```json\n{"winner": "xindian"}\n```')

        response = _generate(client)

        assert "xindian" in response.text  # type: ignore[attr-defined]

    def test_native_structured_output_is_used_when_supported(self) -> None:
        client = _AcceptsOutputConfig()

        _generate(client)

        assert len(client.calls) == 1
        assert "outputConfig" in client.calls[0]

    def test_a_schema_violation_still_fails_loudly(self) -> None:
        # The fallback must not become a way for prose to pass as structured
        # output: validation happens either way.
        client = _RejectsOutputConfig('{"loser": "banqiao"}')

        with pytest.raises(ModelInvocationError, match="invalid structured output"):
            _generate(client)

    def test_unrelated_validation_errors_are_not_retried(self) -> None:
        class _OtherFailure:
            def __init__(self) -> None:
                self.calls = 0

            def converse(self, **kwargs: object) -> dict[str, object]:
                self.calls += 1
                raise botocore.exceptions.ClientError(
                    {"Error": {"Code": "ValidationException", "Message": "bad temperature"}},
                    "Converse",
                )

        client = _OtherFailure()

        with pytest.raises(ModelInvocationError):
            _generate(client)

        assert client.calls == 1, "a non-outputConfig failure must not be retried"
