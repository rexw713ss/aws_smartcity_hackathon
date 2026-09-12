"""SourceConnector Stage 1 proposal for controlled external acquisition.

The backend workstream may amend this boundary as source systems arrive. See
docs/07-project-structure.md and docs/03-ingestion-and-harmonization.md.
"""

from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from youth_compass.domain.types import FileFormat


class DataRequirement(BaseModel):
    """A bounded description of data missing from the published catalog."""

    model_config = ConfigDict(frozen=True)

    topic_terms: tuple[str, ...] = ()
    metric_codes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    time_expression: str | None = None
    accepted_formats: tuple[FileFormat, ...] = (
        FileFormat.CSV,
        FileFormat.JSON,
        FileFormat.EXCEL,
    )


class SourceCandidate(BaseModel):
    """Allowlisted source metadata safe to expose to a reviewer."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    connector_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    download_url: str = Field(pattern=r"^https://")
    file_name: str = Field(min_length=1)
    source_format: FileFormat
    topic_terms: tuple[str, ...] = ()
    metric_codes: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    license: str | None = None
    updated_at: AwareDatetime | None = None
    period_start: str | None = None
    period_end: str | None = None


class AcquiredSource(BaseModel):
    """Private payload returned by a connector before ingestion."""

    model_config = ConfigDict(frozen=True)

    candidate: SourceCandidate
    content: bytes = Field(min_length=1)
    retrieved_at: AwareDatetime


@runtime_checkable
class SourceConnector(Protocol):
    """A bounded connector that never accepts a user-supplied URL."""

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        """Return configured candidates relevant to a missing data requirement."""
        ...

    def get(self, candidate_id: str) -> SourceCandidate | None:
        """Resolve an exact candidate owned by this connector."""
        ...

    def fetch(self, candidate: SourceCandidate) -> AcquiredSource:
        """Retrieve an immutable snapshot of an exact configured candidate."""
        ...
