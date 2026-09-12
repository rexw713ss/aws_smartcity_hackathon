"""SQLite CheckpointStore binding for the contract suite."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from adapters.local import SQLiteCheckpointStore
from tests.contract.registry import register_checkpoint_store
from youth_compass.ports import CheckpointStore


@register_checkpoint_store("sqlite")
@contextmanager
def _sqlite_checkpoint() -> Iterator[CheckpointStore]:
    with tempfile.TemporaryDirectory() as directory:
        yield SQLiteCheckpointStore(Path(directory) / "checkpoints.sqlite3")
