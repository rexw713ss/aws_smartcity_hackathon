"""Controlled source discovery and ingestion handoff."""

from datetime import UTC, datetime

import pytest

from adapters.local import AllowlistedHttpSourceConnector
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
