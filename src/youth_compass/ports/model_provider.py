"""ModelProvider port and its payload models.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.4.

Model output is a proposal, never an executable transformation. Every response is
validated against a schema before any caller acts on it.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    """A single generation request."""

    prompt: str
    system: str | None = None
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    response_schema: dict[str, object] | None = None


class ModelResponse(BaseModel):
    """A generated response and the accounting the provider reported."""

    text: str
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """Foundation-model text generation."""

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a response for ``request``.

        Raises:
            ModelInvocationError: the provider could not produce a response, or
                the response failed schema validation.
        """
        ...
