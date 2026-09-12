"""Amazon Bedrock Converse adapter for schema-constrained model proposals."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from threading import Thread
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

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        """Invoke Bedrock ConverseStream."""
        ...


class BedrockModelProvider:
    """Generate text with Converse and validate requested structured output."""

    def __init__(
        self,
        model_id: str,
        *,
        region: str = "us-east-1",
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
        # Whether this model accepts Converse's native structured-output field.
        # None until an invocation tells us. Amazon Nova accepts it; Anthropic
        # models reject it outright, so we learn once and stop re-sending it.
        self._supports_output_config: bool | None = None
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
                asyncio.to_thread(self._converse_with_schema_fallback, request),
                timeout=self._timeout + 1,
            )
            response = _parse_response(raw, self._model_id)
            if request.response_schema is not None:
                # A truncated response and a schema violation are different bugs
                # with different fixes — raise the token budget versus fix the
                # prompt — so name which one happened instead of reporting both
                # as "invalid structured output".
                if response.stop_reason == "max_tokens":
                    raise ModelInvocationError(
                        "Bedrock hit max_tokens before completing the JSON response; "
                        f"raise ModelRequest.max_tokens above {request.max_tokens}"
                    )
                payload = json.loads(_json_payload(response.text))
                jsonschema.validate(instance=payload, schema=request.response_schema)
            return response
        except TimeoutError as exc:
            raise ModelInvocationError(
                f"Bedrock invocation timed out after {self._timeout:g}s"
            ) from exc
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise ModelInvocationError(f"Bedrock invocation failed: {str(exc)[:300]}") from exc
        except ModelInvocationError:
            raise
        except (json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            raise ModelInvocationError(
                f"Bedrock returned invalid structured output: {str(exc)[:200]}"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelInvocationError("Bedrock returned an invalid Converse response") from exc

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        """Yield text deltas directly from Bedrock's ConverseStream event stream."""

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()

        def emit(item: str | Exception | None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        worker = Thread(target=self._stream_sync, args=(request, emit), daemon=True)
        worker.start()
        try:
            async with asyncio.timeout(self._timeout + 1):
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield item
        except TimeoutError as exc:
            raise ModelInvocationError(
                f"Bedrock streaming invocation timed out after {self._timeout:g}s"
            ) from exc

    def _stream_sync(
        self,
        request: ModelRequest,
        emit: Callable[[str | Exception | None], None],
    ) -> None:
        try:
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
            raw = self._client.converse_stream(**payload)
            events = raw.get("stream")
            if events is None:
                raise TypeError("Bedrock streaming response contains no event stream")
            for event in events:  # type: ignore[union-attr]
                block = _mapping(event)
                content_delta = block.get("contentBlockDelta")
                if content_delta is None:
                    continue
                delta = _mapping(_mapping(content_delta).get("delta"))
                text = delta.get("text")
                if isinstance(text, str) and text:
                    emit(text)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            emit(ModelInvocationError(f"Bedrock streaming invocation failed: {str(exc)[:300]}"))
        except (KeyError, TypeError, ValueError):
            emit(ModelInvocationError("Bedrock returned an invalid ConverseStream response"))
        finally:
            emit(None)

    def _converse_with_schema_fallback(self, request: ModelRequest) -> dict[str, object]:
        """Invoke Converse, adapting to models that reject native structured output.

        Converse's ``outputConfig`` field constrains the response to a JSON
        schema, but only some model families accept it: Amazon Nova does,
        Anthropic models reject the request outright with a ValidationException.
        Rather than restricting the project to one family, ask for the schema
        natively when the model supports it and otherwise instruct the model in
        the prompt and validate the returned JSON, which ``generate`` does either
        way. The capability is remembered so the rejected call happens at most
        once per provider instance.
        """
        wants_schema = request.response_schema is not None
        try:
            return self._converse(request, use_output_config=wants_schema)
        except botocore.exceptions.ClientError as exc:
            if not wants_schema or not _rejects_output_config(exc):
                raise
            self._supports_output_config = False
        return self._converse(request, use_output_config=False)

    def _converse(self, request: ModelRequest, *, use_output_config: bool) -> dict[str, object]:
        wants_schema = request.response_schema is not None
        native_schema = (
            use_output_config and wants_schema and self._supports_output_config is not False
        )

        system_blocks = [{"text": request.system}] if request.system else []
        if wants_schema and not native_schema:
            # The model will not be constrained by the API, so state the contract
            # in the prompt. generate() still validates, so a model that ignores
            # this fails loudly rather than silently returning prose.
            system_blocks.append({"text": _schema_instruction(request.response_schema)})

        payload: dict[str, object] = {
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": request.prompt}]}],
            "inferenceConfig": {
                "maxTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if system_blocks:
            payload["system"] = system_blocks
        if native_schema and request.response_schema is not None:
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
        raw = self._client.converse(**payload)
        if native_schema:
            self._supports_output_config = True
        return raw


def _rejects_output_config(exc: botocore.exceptions.ClientError) -> bool:
    """Whether this error is the model refusing Converse's outputConfig field."""
    error = exc.response.get("Error", {})
    if str(error.get("Code", "")) != "ValidationException":
        return False
    return "outputconfig" in str(error.get("Message", "")).lower()


def _schema_instruction(schema: dict[str, object] | None) -> str:
    """A prompt-level substitute for native schema-constrained output."""
    rendered = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    return (
        "Reply with a single JSON value that validates against this JSON Schema. "
        "Output raw JSON only: no prose, no explanation, and no Markdown code "
        f"fence.\n\nJSON Schema:\n{rendered}"
    )


def _json_payload(text: str) -> str:
    """Extract the JSON value from a response that may be fenced or padded.

    Models instructed to emit bare JSON still wrap it in a ```json fence often
    enough that trusting the raw text would make the fallback path flaky.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        # Drop the opening fence (with any language tag) and the closing fence.
        without_open = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        candidate = without_open.rsplit("```", 1)[0].strip()
    if candidate.startswith(("{", "[")):
        return candidate
    # Fall back to the outermost brace/bracket span, ignoring surrounding prose.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            return candidate[start : end + 1]
    return candidate


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
