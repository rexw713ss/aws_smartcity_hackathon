"""In-memory ModelProvider reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager

from tests.contract.registry import register_model_provider
from youth_compass.ports import ModelProvider, ModelRequest, ModelResponse


class EchoModelProvider:
    """Deterministic provider that echoes the prompt within the token budget."""

    model_id = "reference-echo-1"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        text = request.prompt[: request.max_tokens]
        return ModelResponse(
            text=text,
            model_id=self.model_id,
            input_tokens=len(request.prompt),
            output_tokens=len(text),
            stop_reason="length" if len(request.prompt) > request.max_tokens else "stop",
        )


@register_model_provider("reference")
@contextmanager
def _reference_model_provider() -> Iterator[ModelProvider]:
    # Sync context manager; the adapter's generate() is awaited by the test.
    yield EchoModelProvider()
