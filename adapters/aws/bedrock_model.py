"""Amazon Bedrock Converse adapter for schema-constrained model proposals."""

import asyncio
import json
from copy import deepcopy
from typing import Protocol, cast

import boto3
import botocore.exceptions
import jsonschema
from botocore.config import Config

from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ports import ModelRequest, ModelResponse


class BedrockRuntimeClient(Protocol):
    """Minimal injectable boto3 client surface used by this adapter."""

    def converse(self, **kwargs: object) -> dict[str, object]:
        """Invoke Bedrock Converse."""
        ...


class BedrockModelProvider:
    """Generate text with Converse and validate requested structured output."""

    def __init__(
        self,
        model_id: str,
        *,
        region: str = "ap-northeast-1",
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        client: BedrockRuntimeClient | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("Bedrock model_id must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("Bedrock timeout_seconds must be positive")
        if not 1 <= max_attempts <= 10:
            raise ValueError("Bedrock max_attempts must be between 1 and 10")
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._client = client or cast(
            BedrockRuntimeClient,
            boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(
                    connect_timeout=timeout_seconds,
                    read_timeout=timeout_seconds,
                    retries={"mode": "standard", "total_max_attempts": max_attempts},
                ),
            ),
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Invoke the blocking SDK off-loop and enforce the caller's JSON schema."""

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._converse, request), timeout=self._timeout + 1
            )
            response = _parse_response(raw, self._model_id)
            if request.response_schema is not None:
                payload = json.loads(response.text)
                jsonschema.validate(instance=payload, schema=request.response_schema)
            return response
        except TimeoutError as exc:
            raise ModelInvocationError(
                f"Bedrock invocation timed out after {self._timeout:g}s"
            ) from exc
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise ModelInvocationError(f"Bedrock invocation failed: {str(exc)[:300]}") from exc
        except (json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            raise ModelInvocationError("Bedrock returned invalid structured output") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelInvocationError("Bedrock returned an invalid Converse response") from exc

    def _converse(self, request: ModelRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": request.prompt}]}],
            "inferenceConfig": {
                "maxTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if request.system:
            payload["system"] = [{"text": request.system}]
        if request.response_schema is not None:
            payload["outputConfig"] = {
                "textFormat": {
                    "type": "json_schema",
                    "structure": {
                        "jsonSchema": {
                            "name": "structured_response",
                            "description": "Validated application model proposal",
                            "schema": json.dumps(
                                _bedrock_schema(request.response_schema),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        }
                    },
                }
            }
        return self._client.converse(**payload)


def _parse_response(raw: dict[str, object], model_id: str) -> ModelResponse:
    output = _mapping(raw["output"])
    message = _mapping(output["message"])
    content = message["content"]
    if not isinstance(content, list):
        raise TypeError("Bedrock response content is not a list")
    text_parts = [str(block["text"]) for item in content if "text" in (block := _mapping(item))]
    text = "".join(text_parts)
    if not text:
        raise ValueError("Bedrock response contains no text")
    usage = _mapping(raw.get("usage", {}))
    return ModelResponse(
        text=text,
        model_id=model_id,
        input_tokens=_optional_int(usage.get("inputTokens")),
        output_tokens=_optional_int(usage.get("outputTokens")),
        stop_reason=str(raw["stopReason"]) if raw.get("stopReason") is not None else None,
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("expected a string-keyed mapping")
    return cast(dict[str, object], value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("token usage must be an integer")
    return value


def _bedrock_schema(schema: dict[str, object]) -> dict[str, object]:
    """Remove constraints unsupported by Bedrock's JSON Schema 2020-12 subset."""

    sanitized = deepcopy(schema)
    unsupported = {
        "default",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "maxItems",
        "maxLength",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key in unsupported:
                value.pop(key, None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(sanitized)
    return sanitized
