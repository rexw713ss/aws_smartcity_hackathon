"""HTTPS connector for a fixed, allowlisted source manifest."""

import hashlib
import ipaddress
import re
from datetime import UTC, datetime
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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
_FORMAT_BY_CONTENT_TYPE = {
    "application/csv": FileFormat.CSV,
    "text/csv": FileFormat.CSV,
    "application/json": FileFormat.JSON,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileFormat.EXCEL,
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
            _validate_url(candidate.download_url, self._allowed_hosts)
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
        try:
            content, _ = _download(
                candidate.download_url,
                allowed_hosts=self._allowed_hosts,
                max_download_bytes=self._max_download_bytes,
                timeout_seconds=self._timeout_seconds,
            )
        except _TransportError as exc:
            raise SourceAcquisitionError(
                f"failed to fetch configured source {candidate.candidate_id!r}"
            ) from exc.__cause__
        return AcquiredSource(
            candidate=candidate,
            content=content,
            retrieved_at=datetime.now(UTC),
        )


class LinkSnapshot(BaseModel):
    """Private payload of a reviewer-supplied link before it enters ingestion."""

    model_config = ConfigDict(frozen=True)

    url: str
    host: str
    file_name: str
    source_format: FileFormat
    content: bytes = Field(min_length=1)
    retrieved_at: AwareDatetime


class AllowlistedLinkFetcher:
    """Fetch a link a reviewer pasted, but only from approved official hosts.

    The agent's connectors never take a URL. A person may, because a person can
    point at data the manifest does not list yet. The server still talks only to
    hosts the deployment approved, with the same redirect, type, and size limits
    as a configured source, so a pasted link cannot reach an internal address or
    an arbitrary site. Only the path is the reviewer's choice.
    """

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        max_download_bytes: int = 25 * 1024 * 1024,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not allowed_hosts:
            raise ValueError("a link fetcher requires at least one allowed host")
        if max_download_bytes < 1:
            raise ValueError("max_download_bytes must be positive")
        self._allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self._max_download_bytes = max_download_bytes
        self._timeout_seconds = timeout_seconds

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        return tuple(sorted(self._allowed_hosts))

    def fetch_link(self, url: str) -> LinkSnapshot:
        """Download one reviewer link and name it by the format it actually is."""

        _validate_url(url, self._allowed_hosts)
        try:
            content, content_type = _download(
                url,
                allowed_hosts=self._allowed_hosts,
                max_download_bytes=self._max_download_bytes,
                timeout_seconds=self._timeout_seconds,
            )
        except _TransportError as exc:
            raise SourceAcquisitionError("the link could not be downloaded") from exc.__cause__
        source_format = _link_format(url, content_type)
        return LinkSnapshot(
            url=url,
            host=(urlparse(url).hostname or "").casefold(),
            file_name=_link_file_name(url, source_format),
            source_format=source_format,
            content=content,
            retrieved_at=datetime.now(UTC),
        )


class _TransportError(Exception):
    """A network failure, wrapped so each caller can say what it was fetching."""


def _download(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    max_download_bytes: int,
    timeout_seconds: float,
) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"Accept": ", ".join(sorted(_CONTENT_TYPES)), "User-Agent": "YouthCompass/0.1"},
    )
    try:
        with build_opener(_RejectRedirects()).open(request, timeout=timeout_seconds) as response:
            _validate_url(response.geturl(), allowed_hosts)
            content_type = response.headers.get_content_type().casefold()
            if content_type not in _CONTENT_TYPES:
                raise SourceAcquisitionError(
                    f"source returned unsupported content type {content_type!r}"
                )
            content = response.read(max_download_bytes + 1)
    except SourceAcquisitionError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise _TransportError() from exc
    if len(content) > max_download_bytes:
        raise SourceAcquisitionError(f"source exceeds the {max_download_bytes}-byte download limit")
    if not content:
        raise SourceAcquisitionError("source returned an empty response")
    return content, content_type


def _validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in allowed_hosts:
        raise SourceAcquisitionError("source URL is outside the configured HTTPS allowlist")
    if parsed.username or parsed.password:
        raise SourceAcquisitionError("source URLs may not carry credentials")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    raise SourceAcquisitionError("IP-literal source hosts are not allowed")


def _link_format(url: str, content_type: str) -> FileFormat:
    """Trust what the path says, then what the server says; never guess past that."""

    path = urlparse(url).path.casefold()
    for source_format, extensions in _EXTENSIONS.items():
        if path.endswith(extensions):
            return source_format
    # Open-data portals often serve /api/datasets/<id>/csv/file with no suffix.
    segments = set(path.split("/"))
    for source_format, marker in (
        (FileFormat.CSV, "csv"),
        (FileFormat.JSON, "json"),
        (FileFormat.EXCEL, "xlsx"),
    ):
        if marker in segments:
            return source_format
    declared = _FORMAT_BY_CONTENT_TYPE.get(content_type)
    if declared is None:
        raise SourceAcquisitionError(
            "the link does not say whether it is CSV, JSON, or Excel; "
            "download it and upload the file instead"
        )
    return declared


def _link_file_name(url: str, source_format: FileFormat) -> str:
    extensions = _EXTENSIONS[source_format]
    last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", last).strip("-.")
    if stem.casefold().endswith(extensions):
        return stem[-120:]
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    host = re.sub(r"[^a-z0-9]+", "-", (urlparse(url).hostname or "link").casefold()).strip("-")
    return f"{host}-{digest}{extensions[0]}"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())
