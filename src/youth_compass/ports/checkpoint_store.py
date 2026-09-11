"""CheckpointStore port and its payload model.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Filename fixed by docs/07-project-structure.md section 7.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class WorkflowCheckpoint(BaseModel):
    """Serialized workflow state at one node, for pause and resume."""

    workflow_id: str = Field(min_length=1)
    node: str
    state: dict[str, object] = Field(default_factory=dict)
    saved_at: datetime


@runtime_checkable
class CheckpointStore(Protocol):
    """Durable workflow checkpoints keyed by workflow identifier."""

    def save(self, workflow_id: str, checkpoint: WorkflowCheckpoint) -> None:
        """Persist ``checkpoint`` for ``workflow_id``, replacing any earlier one."""
        ...

    def load(self, workflow_id: str) -> WorkflowCheckpoint | None:
        """Return the stored checkpoint for ``workflow_id``, or ``None``.

        Returning ``None`` for an unknown identifier is deliberate, and is the one
        asymmetry with ObjectStore.get and DataCatalog.get, which raise. A missing
        checkpoint is a normal state for a workflow that has not paused yet.
        """
        ...
