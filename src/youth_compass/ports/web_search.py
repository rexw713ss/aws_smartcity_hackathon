"""Bounded web-search port used by the grounded copilot."""

from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WebSearchRequest(BaseModel):
    """One user-authored search with explicit result and locale bounds."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=600)
    count: int = Field(default=5, ge=1, le=10)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    search_lang: str | None = Field(default=None, pattern=r"^[a-z]{2}(?:-[a-z]{2,4})?$")
    freshness: str | None = Field(
        default=None,
        pattern=r"^(?:pd|pw|pm|py|\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2})$",
    )


class WebSearchResult(BaseModel):
    """Public, bounded projection of one provider result."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https://", max_length=2_000)
    description: str = Field(default="", max_length=2_000)
    published_at: AwareDatetime | None = None


@runtime_checkable
class WebSearchProvider(Protocol):
    """Search the public web without granting arbitrary URL fetching."""

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchResult, ...]:
        """Return provider-ranked results subject to the request bounds."""
        ...
