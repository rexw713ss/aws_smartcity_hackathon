"""Controlled source discovery and ingestion handoff."""

from datetime import UTC, datetime

import pytest

from adapters.local import AllowlistedHttpSourceConnector, AllowlistedLinkFetcher
from adapters.local.http_source import (
    LinkSnapshot,
    _landing_page_data_links,
    _link_file_name,
    _link_format,
)
from youth_compass.acquisition import AcquiredSource, DataAcquisitionService
from youth_compass.domain import FileFormat, SourceAcquisitionError
from youth_compass.ports import (
    DataRequirement,
    JobReference,
    JobStatus,
    SourceCandidate,
)


def _candidate(candidate_id: str = "ntpc-population") -> SourceCandidate:
    return SourceCandidate(
        candidate_id=candidate_id,
        connector_id="taiwan_open_data",
        title="New Taipei youth population",
        publisher="New Taipei City Government",
        download_url="https://data.example.gov.tw/population.csv",
        file_name="population.csv",
        source_format=FileFormat.CSV,
        topic_terms=("population",),
        metric_codes=("population_count",),
        entity_ids=("banqiao", "linkou"),
        license="Open Government Data License 1.0",
    )


class FakeConnector:
    def __init__(self, candidate: SourceCandidate) -> None:
        self.candidate = candidate

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        if "population_count" in requirement.metric_codes:
            return (self.candidate,)
        return ()

    def get(self, candidate_id: str) -> SourceCandidate | None:
        return self.candidate if candidate_id == self.candidate.candidate_id else None

    def fetch(self, candidate: SourceCandidate) -> AcquiredSource:
        return AcquiredSource(
            candidate=candidate,
            content=b"year,district,population\n2025,Banqiao,100\n",
            retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
        )


class FakeIngestion:
    def __init__(self) -> None:
        self.submission: dict[str, object] | None = None

    def submit_bytes(
        self,
        *,
        file_name: str,
        content: bytes,
        submitted_by: str,
        topic_hint: str | None = None,
    ) -> JobReference:
        self.submission = {
            "file_name": file_name,
            "content": content,
            "submitted_by": submitted_by,
            "topic_hint": topic_hint,
        }
        return JobReference(
            job_id="job-acquired",
            status=JobStatus.AWAITING_APPROVAL,
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
        )


def test_discovery_ranks_and_selected_source_enters_ingestion() -> None:
    candidate = _candidate()
    ingestion = FakeIngestion()
    service = DataAcquisitionService((FakeConnector(candidate),), ingestion)

    matches = service.discover(
        DataRequirement(metric_codes=("population_count",), entity_ids=("banqiao",))
    )
    started = service.start(candidate.candidate_id, submitted_by="reviewer@example.com")

    assert matches == (candidate,)
    assert started.ingestion_status == "awaiting_approval"
    assert ingestion.submission == {
        "file_name": "population.csv",
        "content": b"year,district,population\n2025,Banqiao,100\n",
        "submitted_by": "reviewer@example.com",
        "topic_hint": "population",
    }


def test_unknown_candidate_is_not_treated_as_a_url() -> None:
    service = DataAcquisitionService((FakeConnector(_candidate()),), FakeIngestion())

    with pytest.raises(SourceAcquisitionError, match="unknown source candidate"):
        service.start("unregistered-source", submitted_by="reviewer@example.com")


def test_http_connector_rejects_sources_outside_host_allowlist() -> None:
    with pytest.raises(SourceAcquisitionError, match="allowlist"):
        AllowlistedHttpSourceConnector(
            "taiwan_open_data",
            (_candidate(),),
            allowed_hosts=frozenset({"approved.example.gov.tw"}),
        )


class FakeLinkFetcher:
    allowed_hosts = ("data.ntpc.gov.tw",)

    def __init__(self) -> None:
        self.requested: list[str] = []

    def fetch_link(self, url: str) -> LinkSnapshot:
        self.requested.append(url)
        return LinkSnapshot(
            url=url,
            host="data.ntpc.gov.tw",
            file_name="housing-stock.csv",
            source_format=FileFormat.CSV,
            content=b"district,housing_units\nLinkou,100\n",
            retrieved_at=datetime(2026, 9, 13, tzinfo=UTC),
        )


def test_reviewer_link_enters_the_same_approval_gated_ingestion() -> None:
    ingestion = FakeIngestion()
    fetcher = FakeLinkFetcher()
    service = DataAcquisitionService((), ingestion, link_fetcher=fetcher)

    started = service.start_from_link(
        "https://data.ntpc.gov.tw/api/datasets/abc/csv/file",
        submitted_by="reviewer@example.gov.tw",
        topic_hint="housing",
    )

    assert fetcher.requested == ["https://data.ntpc.gov.tw/api/datasets/abc/csv/file"]
    assert started.ingestion_job_id == "job-acquired"
    assert started.ingestion_status == JobStatus.AWAITING_APPROVAL.value
    assert started.source_format is FileFormat.CSV
    assert ingestion.submission == {
        "file_name": "housing-stock.csv",
        "content": b"district,housing_units\nLinkou,100\n",
        "submitted_by": "reviewer@example.gov.tw",
        "topic_hint": "housing",
    }
    assert service.link_hosts == ("data.ntpc.gov.tw",)


def test_reviewer_link_is_refused_when_links_are_not_enabled() -> None:
    service = DataAcquisitionService((), FakeIngestion())

    assert service.link_hosts == ()
    with pytest.raises(SourceAcquisitionError, match="not enabled"):
        service.start_from_link("https://data.ntpc.gov.tw/a.csv", submitted_by="reviewer")


@pytest.mark.parametrize(
    "url",
    [
        "http://data.ntpc.gov.tw/a.csv",
        "https://evil.example.com/a.csv",
        "https://data.ntpc.gov.tw.evil.example.com/a.csv",
        "https://169.254.169.254/latest/meta-data",
        "https://user:secret@data.ntpc.gov.tw/a.csv",
    ],
)
def test_link_fetcher_refuses_links_before_any_network_call(url: str) -> None:
    fetcher = AllowlistedLinkFetcher(allowed_hosts=frozenset({"data.ntpc.gov.tw"}))

    with pytest.raises(SourceAcquisitionError):
        fetcher.fetch_link(url)


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    [
        (
            "https://data.ntpc.gov.tw/files/housing.xlsx",
            "application/octet-stream",
            FileFormat.EXCEL,
        ),
        ("https://data.ntpc.gov.tw/api/datasets/abc/csv/file", "text/plain", FileFormat.CSV),
        ("https://data.ntpc.gov.tw/api/datasets/abc/json", "text/plain", FileFormat.JSON),
        ("https://data.ntpc.gov.tw/download?id=1", "text/csv", FileFormat.CSV),
    ],
)
def test_link_format_trusts_the_path_then_the_declared_type(
    url: str, content_type: str, expected: FileFormat
) -> None:
    assert _link_format(url, content_type) is expected


def test_link_format_refuses_to_guess() -> None:
    with pytest.raises(SourceAcquisitionError, match="upload the file"):
        _link_format("https://data.ntpc.gov.tw/download?id=1", "application/octet-stream")


def test_link_file_name_keeps_a_real_name_and_invents_a_safe_one_otherwise() -> None:
    assert (
        _link_file_name("https://data.ntpc.gov.tw/files/housing_2025.csv", FileFormat.CSV)
        == "housing_2025.csv"
    )
    invented = _link_file_name("https://data.ntpc.gov.tw/api/datasets/abc/csv/file", FileFormat.CSV)
    assert invented.startswith("data-ntpc-gov-tw-")
    assert invented.endswith(".csv")


def test_landing_page_extracts_same_host_data_links_without_executing_html() -> None:
    content = b"""
        <html><body>
          <a href="/files/housing.csv">CSV</a>
          <a href="https://evil.example.com/stolen.csv">external</a>
          <script>const api = '/api/datasets/abc-123/json';</script>
        </body></html>
    """

    links = _landing_page_data_links(
        "https://data.ntpc.gov.tw/datasets/housing",
        content,
        frozenset({"data.ntpc.gov.tw"}),
    )

    assert links == (
        "https://data.ntpc.gov.tw/files/housing.csv",
        "https://data.ntpc.gov.tw/api/datasets/abc-123/json",
    )


def test_landing_page_does_not_treat_ordinary_navigation_as_data() -> None:
    links = _landing_page_data_links(
        "https://data.ntpc.gov.tw/datasets/housing",
        b'<a href="/about">About</a><a href="/datasets/other">Other dataset</a>',
        frozenset({"data.ntpc.gov.tw"}),
    )

    assert links == ()


def test_link_fetcher_resolves_landing_page_before_creating_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Headers:
        def __init__(self, content_type: str) -> None:
            self._content_type = content_type

        def get_content_type(self) -> str:
            return self._content_type

    class Response:
        def __init__(self, url: str, content_type: str, content: bytes) -> None:
            self._url = url
            self.headers = Headers(content_type)
            self._content = content

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return self._url

        def read(self, limit: int) -> bytes:
            return self._content[:limit]

    landing_url = "https://data.ntpc.gov.tw/datasets/housing"
    csv_url = "https://data.ntpc.gov.tw/api/datasets/abc-123/csv"
    responses = iter(
        (
            Response(landing_url, "text/html", b'<a href="/api/datasets/abc-123/csv">CSV</a>'),
            Response(csv_url, "text/csv", b"district,value\nLinkou,100\n"),
        )
    )
    requested: list[str] = []

    class Opener:
        def open(self, request: object, *, timeout: float) -> Response:
            del timeout
            requested.append(request.full_url)  # type: ignore[attr-defined]
            return next(responses)

    monkeypatch.setattr("adapters.local.http_source.build_opener", lambda *args: Opener())
    fetcher = AllowlistedLinkFetcher(allowed_hosts=frozenset({"data.ntpc.gov.tw"}))

    snapshot = fetcher.fetch_link(landing_url)

    assert requested == [landing_url, csv_url]
    assert snapshot.url == csv_url
    assert snapshot.source_format is FileFormat.CSV
    assert snapshot.content == b"district,value\nLinkou,100\n"
