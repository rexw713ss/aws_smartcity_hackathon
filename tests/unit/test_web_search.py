"""Brave adapter and grounded web-search orchestration tests."""

import asyncio
import json
from datetime import UTC, datetime

from adapters.local.brave_search import BraveWebSearchProvider
from youth_compass.agent import CopilotStatus, GroundedCopilotService
from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    DecisionProfileRegistry,
    FeatureRegistry,
)
from youth_compass.domain.errors import WebSearchError
from youth_compass.ports import WebSearchRequest, WebSearchResult


class EmptyFeatureProvider:
    def get_features(self, query: object) -> object:
        raise AssertionError(f"web search must not query feature storage: {query!r}")


class StaticWebSearch:
    def __init__(self, results: tuple[WebSearchResult, ...] = (), *, failure: bool = False) -> None:
        self.results = results
        self.failure = failure
        self.requests: list[WebSearchRequest] = []

    async def search(self, request: WebSearchRequest) -> tuple[WebSearchResult, ...]:
        self.requests.append(request)
        if self.failure:
            raise WebSearchError("provider unavailable")
        return self.results


def _service(search: StaticWebSearch) -> GroundedCopilotService:
    return GroundedCopilotService(
        feature_provider=EmptyFeatureProvider(),  # type: ignore[arg-type]
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        web_search=search,
    )


def test_web_question_routes_to_brave_results_with_separate_citations() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="New Taipei youth policy update",
                url="https://example.gov.tw/news/1",
                description="A current official announcement.",
                published_at=datetime(2026, 9, 13, tzinfo=UTC),
            ),
        )
    )

    response = asyncio.run(_service(search).answer("Tìm trên web tin mới về chính sách thanh niên"))

    assert response.status is CopilotStatus.ANSWERED
    assert response.citations == ()
    assert response.web_citations[0].citation_id == "web-1"
    assert response.web_citations[0].url == "https://example.gov.tw/news/1"
    assert "[web-1]" in response.answer
    assert search.requests[0].country == "TW"
    assert search.requests[0].search_lang == "vi"
    assert [item.tool for item in response.tool_trace] == [
        "query_decomposer",
        "web_search",
        "answer_composer",
    ]


def test_web_provider_failure_returns_no_web_claim() -> None:
    response = asyncio.run(
        _service(StaticWebSearch(failure=True)).answer("Search the web for news")
    )

    assert response.status is CopilotStatus.INSUFFICIENT_DATA
    assert response.web_citations == ()
    assert response.tool_trace[-1].outcome == "failed"


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_brave_adapter_parses_and_deduplicates_https_results(monkeypatch: object) -> None:
    requests = []

    def fake_urlopen(request: object, *, timeout: float) -> FakeHttpResponse:
        requests.append((request, timeout))
        return FakeHttpResponse(
            {
                "web": {
                    "results": [
                        {
                            "title": "Official result",
                            "url": "https://example.gov.tw/page",
                            "description": "Verified snippet",
                            "page_age": "2026-09-13T00:00:00Z",
                        },
                        {
                            "title": "Duplicate",
                            "url": "https://example.gov.tw/page",
                            "description": "Duplicate URL",
                        },
                    ]
                }
            }
        )

    monkeypatch.setattr("adapters.local.brave_search.urlopen", fake_urlopen)  # type: ignore[attr-defined]
    provider = BraveWebSearchProvider("secret-key", timeout_seconds=7)
    results = asyncio.run(provider.search(WebSearchRequest(query="youth policy", count=5)))

    assert len(results) == 1
    assert results[0].title == "Official result"
    assert results[0].published_at == datetime(2026, 9, 13, tzinfo=UTC)
    request, timeout = requests[0]
    assert timeout == 7
    assert "q=youth+policy" in request.full_url
    assert request.get_header("X-subscription-token") == "secret-key"
