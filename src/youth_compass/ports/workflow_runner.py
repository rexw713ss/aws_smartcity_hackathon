"""WorkflowRunner port and its payload models.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.6.

PROPOSED ADDITION: docs/07-project-structure.md section 7 fixes eight port
filenames and omits WorkflowRunner, even though docs/01 section 5.6 defines the
Protocol. This module is therefore proposed as a ninth entry in that section,
named by the snake_case form of the Protocol name.

The approval pause is the reason this port exists: an adapter may hold a callback
token so a human decision resumes a suspended workflow. The model cannot mint an
approval identity.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """Lifecycle of an ingestion job."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHED = "published"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    FAILED = "failed"


class IngestionRequest(BaseModel):
    """A request to onboard one source file."""

    source_uri: str
    submitted_by: str
    topic_hint: str | None = None


class JobReference(BaseModel):
    """A started ingestion job."""

    job_id: str = Field(min_length=1)
    status: JobStatus
    created_at: datetime
    callback_token: str | None = None


class ApprovalDecision(BaseModel):
    """A reviewer's decision on a paused mapping proposal."""

    approved: bool
    decided_by: str = Field(min_length=1)
    decided_at: datetime
    notes: str | None = None
    mapping_overrides: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class WorkflowRunner(Protocol):
    """Ingestion workflow orchestration with a human-approval pause."""

    def start_ingestion(self, request: IngestionRequest) -> JobReference:
        """Start an ingestion workflow and return its reference."""
        ...

    def resume_after_approval(self, job_id: str, decision: ApprovalDecision) -> None:
        """Resume the paused workflow ``job_id`` with ``decision``.

        Raises:
            WorkflowStateError: ``job_id`` is unknown, or already settled.
        """
        ...
