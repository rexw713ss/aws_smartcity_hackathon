"""HTTPS connector for a fixed, allowlisted source manifest."""

import ipaddress
from datetime import UTC, datetime
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from youth_compass.domain.errors import SourceAcquisitionError
from youth_compass.domain.types import FileFormat
from youth_compass.ports import AcquiredSource, DataRequirement, SourceCandidate

_CONTENT_TYPES = {
    "application/csv",
    "application/json",
    "application/octet-stream",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
}
_EXTENSIONS = {
    FileFormat.CSV: (".csv", ".tsv"),
    FileFormat.EXCEL: (".xlsx", ".xlsm"),
    FileFormat.JSON: (".json", ".jsonl", ".ndjson"),
}


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        raise SourceAcquisitionError("source redirects are not allowed")


class AllowlistedHttpSourceConnector:
    """Fetch only candidates fixed at construction time from approved HTTPS hosts."""

    def __init__(
        self,
        connector_id: str,
        candidates: tuple[SourceCandidate, ...],
        *,
        allowed_hosts: frozenset[str],
        max_download_bytes: int = 25 * 1024 * 1024,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not allowed_hosts:
            raise ValueError("an HTTP source connector requires at least one allowed host")
        if max_download_bytes < 1:
            raise ValueError("max_download_bytes must be positive")
        self._connector_id = connector_id
        self._allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self._max_download_bytes = max_download_bytes
        self._timeout_seconds = timeout_seconds
        self._candidates: dict[str, SourceCandidate] = {}
        for candidate in candidates:
            if candidate.connector_id != connector_id:
                raise ValueError(
                    f"candidate {candidate.candidate_id!r} belongs to another connector"
                )
            self._validate_url(candidate.download_url)
            if not candidate.file_name.casefold().endswith(
                _EXTENSIONS.get(candidate.source_format, ())
            ):
                raise ValueError(
                    f"candidate {candidate.candidate_id!r} filename does not match its format"
                )
            if candidate.candidate_id in self._candidates:
                raise ValueError(f"duplicate source candidate {candidate.candidate_id!r}")
            self._candidates[candidate.candidate_id] = candidate

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        """Return format-compatible candidates with at least one semantic match."""

        required = {
            *requirement.topic_terms,
            *requirement.metric_codes,
            *requirement.entity_ids,
        }
        normalized_required = {_normalize(item) for item in required}
        return tuple(
            candidate
            for candidate in self._candidates.values()
            if candidate.source_format in requirement.accepted_formats
            and normalized_required
            & {
                _normalize(item)
                for item in (
                    *candidate.topic_terms,
                    *candidate.metric_codes,
                    *candidate.entity_ids,
                )
            }
        )

    def get(self, candidate_id: str) -> SourceCandidate | None:
        return self._candidates.get(candidate_id)

    def fetch(self, candidate: SourceCandidate) -> AcquiredSource:
        """Download a configured source with redirect, type, and byte limits."""

        configured = self.get(candidate.candidate_id)
        if configured is None or configured != candidate:
            raise SourceAcquisitionError("source candidate is not registered by this connector")
        request = Request(
            candidate.download_url,
            headers={"Accept": ", ".join(sorted(_CONTENT_TYPES)), "User-Agent": "YouthCompass/0.1"},
        )
        try:
            with build_opener(_RejectRedirects()).open(
                request, timeout=self._timeout_seconds
            ) as response:
                self._validate_url(response.geturl())
                content_type = response.headers.get_content_type().casefold()
                if content_type not in _CONTENT_TYPES:
                    raise SourceAcquisitionError(
                        f"source returned unsupported content type {content_type!r}"
                    )
                content = response.read(self._max_download_bytes + 1)
        except SourceAcquisitionError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise SourceAcquisitionError(
                f"failed to fetch configured source {candidate.candidate_id!r}"
            ) from exc
        if len(content) > self._max_download_bytes:
            raise SourceAcquisitionError(
                f"source exceeds the {self._max_download_bytes}-byte download limit"
            )
        if not content:
            raise SourceAcquisitionError("source returned an empty response")
        return AcquiredSource(
            candidate=candidate,
            content=content,
            retrieved_at=datetime.now(UTC),
        )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or host not in self._allowed_hosts:
            raise SourceAcquisitionError("source URL is outside the configured HTTPS allowlist")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return
        raise SourceAcquisitionError("IP-literal source hosts are not allowed")


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())
