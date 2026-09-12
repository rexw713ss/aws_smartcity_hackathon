"""Amazon Bedrock ModelProvider request, response, and failure boundaries."""

import asyncio
import json

import botocore.exceptions
import pytest

from adapters.aws.bedrock_model import BedrockModelProvider
from youth_compass.domain import ModelInvocationError
from youth_compass.ports import ModelRequest


class FakeBedrockClient:
    def __init__(self, response: dict[str, object] | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(text: str) -> dict[str, object]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": {"inputTokens": 12, "outputTokens": 7, "totalTokens": 19},
        "stopReason": "end_turn",
    }


def test_bedrock_converse_uses_structured_output_and_reports_usage() -> None:
    client = FakeBedrockClient(_response('{"name":"population"}'))
    provider = BedrockModelProvider("test-model", client=client)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1}},
        "required": ["name"],
    }

    result = asyncio.run(
        provider.generate(
            ModelRequest(
                system="Return a dataset subject.",
                prompt="population trend",
                max_tokens=200,
                response_schema=schema,
            )
        )
    )

    call = client.calls[0]
    assert call["modelId"] == "test-model"
    assert call["system"] == [{"text": "Return a dataset subject."}]
    output_config = call["outputConfig"]
    assert isinstance(output_config, dict)
    encoded_schema = output_config["textFormat"]["structure"]["jsonSchema"]["schema"]
    bedrock_schema = json.loads(encoded_schema)
    assert bedrock_schema["additionalProperties"] is False
    assert "minLength" not in bedrock_schema["properties"]["name"]
    assert result.text == '{"name":"population"}'
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.stop_reason == "end_turn"


def test_bedrock_rejects_output_that_violates_original_schema() -> None:
    provider = BedrockModelProvider(
        "test-model", client=FakeBedrockClient(_response('{"wrong":"value"}'))
    )

    with pytest.raises(ModelInvocationError, match="invalid structured output"):
        asyncio.run(
            provider.generate(
                ModelRequest(
                    prompt="population",
                    response_schema={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                )
            )
        )


def test_bedrock_translates_sdk_failures() -> None:
    error = botocore.exceptions.EndpointConnectionError(
        endpoint_url="https://bedrock-runtime.invalid"
    )
    provider = BedrockModelProvider("test-model", client=FakeBedrockClient(error))

    with pytest.raises(ModelInvocationError, match="Bedrock invocation failed"):
        asyncio.run(provider.generate(ModelRequest(prompt="hello")))
