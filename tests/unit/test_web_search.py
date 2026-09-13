"""Brave adapter and grounded web-search orchestration tests."""

import asyncio
import json
from datetime import UTC, datetime

from adapters.local.brave_search import BraveWebSearchProvider
from youth_compass.acquisition import DataAcquisitionService
from youth_compass.agent import CopilotStatus, GroundedCopilotService
from youth_compass.decisioning import (
    DEFAULT_DECISION_PROFILES,
    DEFAULT_FEATURES,
    DecisionProfileRegistry,
    FeatureQuery,
    FeatureRegistry,
    FeatureSet,
)
from youth_compass.domain import FileFormat
from youth_compass.domain.errors import WebSearchError
from youth_compass.ports import DataRequirement, SourceCandidate, WebSearchRequest, WebSearchResult


class EmptyFeatureProvider:
    def get_features(self, query: object) -> object:
        raise AssertionError(f"web search must not query feature storage: {query!r}")


class MissingFeatureProvider:
    def get_features(self, query: FeatureQuery) -> FeatureSet:
        return FeatureSet(values=())


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


class StaticSourceConnector:
    candidate = SourceCandidate(
        candidate_id="configured-housing",
        connector_id="test",
        title="Configured housing source",
        publisher="New Taipei City Government",
        download_url="https://data.ntpc.gov.tw/configured.csv",
        file_name="configured.csv",
        source_format=FileFormat.CSV,
        topic_terms=("housing",),
    )

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        return (self.candidate,)

    def get(self, candidate_id: str) -> SourceCandidate | None:
        return self.candidate if candidate_id == self.candidate.candidate_id else None

    def fetch(self, candidate: SourceCandidate) -> object:
        raise AssertionError(f"source discovery must not fetch {candidate!r}")


class NoopIngestion:
    def submit_bytes(self, **kwargs: object) -> object:
        raise AssertionError(f"source discovery must not ingest {kwargs!r}")


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


def _missing_data_service(search: StaticWebSearch) -> GroundedCopilotService:
    return GroundedCopilotService(
        feature_provider=MissingFeatureProvider(),
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        web_search=search,
        source_search_hosts=("data.ntpc.gov.tw",),
    )


def test_missing_data_searches_only_approved_hosts_for_source_suggestions() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="Official housing open data",
                url="https://data.ntpc.gov.tw/datasets/housing.csv",
                description="Housing market data published by New Taipei City.",
            ),
            WebSearchResult(
                title="Unapproved mirror",
                url="https://downloads.example.com/housing.csv",
                description="A copy outside the approved government hosts.",
            ),
        )
    )

    response = asyncio.run(_missing_data_service(search).answer("Where should I buy a home?"))

    assert response.status is CopilotStatus.ACQUISITION_REQUIRED
    assert response.data_requirement is not None
    assert response.source_candidates == ()
    assert [citation.url for citation in response.web_citations] == [
        "https://data.ntpc.gov.tw/datasets/housing.csv"
    ]
    assert response.answer == (
        "I searched approved government sites and found 1 more possible source(s)."
    )
    assert "site:data.ntpc.gov.tw" in search.requests[0].query
    assert "開放資料" in search.requests[0].query
    assert "filetype:" not in search.requests[0].query
    assert response.tool_trace[-1].tool == "discover_web_sources"
    assert response.tool_trace[-1].outcome == "candidates"
    assert any("not evidence" in warning for warning in response.warnings)


def test_missing_data_does_not_offer_html_landing_pages_for_ingestion() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="Housing dataset catalogue page",
                url="https://data.ntpc.gov.tw/datasets/housing",
                description="Dataset metadata and a download button.",
            ),
            WebSearchResult(
                title="Housing data download",
                url="https://data.ntpc.gov.tw/api/datasets/housing/csv/file",
                description="Direct CSV export.",
            ),
        )
    )

    response = asyncio.run(_missing_data_service(search).answer("Where should I buy a home?"))

    assert [citation.url for citation in response.web_citations] == [
        "https://data.ntpc.gov.tw/api/datasets/housing/csv/file"
    ]
    assert "rejected 1 landing page(s)" in response.tool_trace[-1].summary


def test_missing_data_reports_when_search_only_finds_landing_pages() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="Housing dataset catalogue page",
                url="https://data.ntpc.gov.tw/datasets/housing",
                description="Dataset metadata and a download button.",
            ),
        )
    )

    response = asyncio.run(_missing_data_service(search).answer("Where should I buy a home?"))

    assert response.web_citations == ()
    assert any("landing pages" in warning for warning in response.warnings)


def test_missing_data_resolves_same_host_api_endpoint_from_search_snippet() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="NTPC OpenData API",
                url="https://data.ntpc.gov.tw/openapi/swagger-ui/index.html",
                description=(
                    "GET /api/datasets/34b402a8-53d9-483d-9406-24a682c2d6dc/csv "
                    "Bus stop information"
                ),
            ),
        )
    )

    response = asyncio.run(_missing_data_service(search).answer("Where should I buy a home?"))

    assert [citation.url for citation in response.web_citations] == [
        "https://data.ntpc.gov.tw/api/datasets/34b402a8-53d9-483d-9406-24a682c2d6dc/csv"
    ]
    assert "resolved 1 landing page(s)" in response.tool_trace[-1].summary


def test_missing_data_searches_web_even_when_a_configured_source_exists() -> None:
    search = StaticWebSearch(
        (
            WebSearchResult(
                title="Another official housing source",
                url="https://data.ntpc.gov.tw/discovered.csv",
                description="A current government dataset.",
            ),
        )
    )
    acquisition = DataAcquisitionService(
        (StaticSourceConnector(),),
        NoopIngestion(),  # type: ignore[arg-type]
    )
    service = GroundedCopilotService(
        feature_provider=MissingFeatureProvider(),
        feature_registry=FeatureRegistry(DEFAULT_FEATURES),
        profile_registry=DecisionProfileRegistry(DEFAULT_DECISION_PROFILES),
        acquisition=acquisition,
        web_search=search,
        source_search_hosts=("data.ntpc.gov.tw",),
    )

    response = asyncio.run(service.answer("Where should I buy a home?"))

    assert [item.candidate_id for item in response.source_candidates] == ["configured-housing"]
    assert [item.url for item in response.web_citations] == [
        "https://data.ntpc.gov.tw/discovered.csv"
    ]
    assert response.tool_trace[-1].tool == "discover_web_sources"
    assert len(search.requests) == 1


def test_missing_data_web_failure_preserves_the_grounded_refusal() -> None:
    response = asyncio.run(
        _missing_data_service(StaticWebSearch(failure=True)).answer("Where should I buy a home?")
    )

    assert response.status is CopilotStatus.INSUFFICIENT_DATA
    assert response.web_citations == ()
    assert response.tool_trace[-1].tool == "discover_web_sources"
    assert response.tool_trace[-1].outcome == "failed"
    assert any("unavailable" in warning for warning in response.warnings)


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
                            "title": "Insecure result",
                            "url": "http://example.gov.tw/insecure",
                            "description": "Must be skipped without losing valid siblings",
                        },
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
