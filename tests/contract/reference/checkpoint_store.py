"""In-memory CheckpointStore reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager

from tests.contract.registry import register_checkpoint_store
from youth_compass.ports import CheckpointStore, WorkflowCheckpoint


class InMemoryCheckpointStore:
    """Keyed by workflow id; ``load`` returns ``None`` for an unknown id."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, WorkflowCheckpoint] = {}

    def save(self, workflow_id: str, checkpoint: WorkflowCheckpoint) -> None:
        self._checkpoints[workflow_id] = checkpoint

    def load(self, workflow_id: str) -> WorkflowCheckpoint | None:
        return self._checkpoints.get(workflow_id)


@register_checkpoint_store("reference")
@contextmanager
def _reference_checkpoint_store() -> Iterator[CheckpointStore]:
    yield InMemoryCheckpointStore()
