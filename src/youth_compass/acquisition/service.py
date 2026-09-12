"""Source discovery, relevance ranking, and ingestion handoff."""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from youth_compass.acquisition.contracts import AcquisitionStart, LinkAcquisitionStart
from youth_compass.domain.errors import SourceAcquisitionError
from youth_compass.domain.types import FileFormat
from youth_compass.ports.source_connector import DataRequirement, SourceCandidate, SourceConnector
from youth_compass.ports.workflow_runner import JobReference


class IngestionSubmitter(Protocol):
    """Narrow workflow boundary required after a source is fetched."""

    def submit_bytes(
        self,
        *,
        file_name: str,
        content: bytes,
        submitted_by: str,
        topic_hint: str | None = None,
    ) -> JobReference: ...


class LinkPayload(Protocol):
    """What a link fetcher hands back: enough to name the file and submit it."""

    @property
    def url(self) -> str: ...
    @property
    def host(self) -> str: ...
    @property
    def file_name(self) -> str: ...
    @property
    def source_format(self) -> FileFormat: ...
    @property
    def content(self) -> bytes: ...
    @property
    def retrieved_at(self) -> datetime: ...


class LinkFetcher(Protocol):
    """Guarded download of a reviewer-supplied link from approved hosts only."""

    @property
    def allowed_hosts(self) -> tuple[str, ...]: ...

    def fetch_link(self, url: str) -> LinkPayload: ...


class DataAcquisitionService:
    """Discover only configured sources and submit selected snapshots for review."""

    def __init__(
        self,
        connectors: Iterable[SourceConnector],
        ingestion: IngestionSubmitter,
        *,
        result_limit: int = 5,
        link_fetcher: LinkFetcher | None = None,
    ) -> None:
        if result_limit < 1:
            raise ValueError("result_limit must be positive")
        self._connectors = tuple(connectors)
        self._ingestion = ingestion
        self._result_limit = result_limit
        self._link_fetcher = link_fetcher

    @property
    def link_hosts(self) -> tuple[str, ...]:
        """Hosts a reviewer link may point at; empty when links are switched off."""

        return self._link_fetcher.allowed_hosts if self._link_fetcher is not None else ()

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        """Return deterministic, deduplicated candidates ordered by semantic overlap."""

        candidates: dict[str, SourceCandidate] = {}
        for connector in self._connectors:
            for candidate in connector.discover(requirement):
                existing = candidates.get(candidate.candidate_id)
                if existing is not None:
                    raise SourceAcquisitionError(
                        f"duplicate source candidate {candidate.candidate_id!r}"
                    )
                candidates[candidate.candidate_id] = candidate
        ranked = sorted(
            candidates.values(),
            key=lambda item: (-_relevance(item, requirement), item.candidate_id),
        )
        return tuple(ranked[: self._result_limit])

    def start(self, candidate_id: str, *, submitted_by: str) -> AcquisitionStart:
        """Fetch one allowlisted candidate and enter the existing approval workflow."""

        connector, candidate = self._resolve(candidate_id)
        acquired = connector.fetch(candidate)
        if acquired.candidate != candidate:
            raise SourceAcquisitionError("connector returned a different source candidate")
        topic_hint = candidate.topic_terms[0] if candidate.topic_terms else None
        reference = self._ingestion.submit_bytes(
            file_name=candidate.file_name,
            content=acquired.content,
            submitted_by=submitted_by,
            topic_hint=topic_hint,
        )
        return AcquisitionStart(
            candidate=candidate,
            ingestion_job_id=reference.job_id,
            ingestion_status=reference.status.value,
            created_at=reference.created_at,
        )

    def start_from_link(
        self,
        url: str,
        *,
        submitted_by: str,
        topic_hint: str | None = None,
    ) -> LinkAcquisitionStart:
        """Fetch a reviewer link and enter the same approval-gated workflow.

        Nothing is published from here. The snapshot is mapped, quality-checked,
        and held for approval exactly like a configured source or an upload.
        """

        if self._link_fetcher is None:
            raise SourceAcquisitionError("submitting data by link is not enabled")
        snapshot = self._link_fetcher.fetch_link(url)
        reference = self._ingestion.submit_bytes(
            file_name=snapshot.file_name,
            content=snapshot.content,
            submitted_by=submitted_by,
            topic_hint=topic_hint,
        )
        return LinkAcquisitionStart(
            url=snapshot.url,
            host=snapshot.host,
            file_name=snapshot.file_name,
            source_format=snapshot.source_format,
            ingestion_job_id=reference.job_id,
            ingestion_status=reference.status.value,
            created_at=reference.created_at,
        )

    def _resolve(self, candidate_id: str) -> tuple[SourceConnector, SourceCandidate]:
        matches = [
            (connector, candidate)
            for connector in self._connectors
            if (candidate := connector.get(candidate_id)) is not None
        ]
        if not matches:
            raise SourceAcquisitionError(f"unknown source candidate {candidate_id!r}")
        if len(matches) > 1:
            raise SourceAcquisitionError(f"ambiguous source candidate {candidate_id!r}")
        return matches[0]


def _relevance(candidate: SourceCandidate, requirement: DataRequirement) -> int:
    required = {
        *requirement.topic_terms,
        *requirement.metric_codes,
        *requirement.entity_ids,
    }
    offered = {
        *candidate.topic_terms,
        *candidate.metric_codes,
        *candidate.entity_ids,
    }
    return len({_normalized(item) for item in required} & {_normalized(item) for item in offered})


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())
