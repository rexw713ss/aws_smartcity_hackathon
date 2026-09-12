"""SQLite-backed durable workflow checkpoints."""

import sqlite3
from pathlib import Path

from youth_compass.domain.errors import WorkflowPersistenceError
from youth_compass.ports import WorkflowCheckpoint


class SQLiteCheckpointStore:
    """Persist the latest validated checkpoint for each workflow."""

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()
        try:
            self._database.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                        workflow_id TEXT PRIMARY KEY,
                        checkpoint_json TEXT NOT NULL,
                        saved_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_history (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        workflow_id TEXT NOT NULL,
                        checkpoint_json TEXT NOT NULL,
                        saved_at TEXT NOT NULL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise WorkflowPersistenceError(
                f"cannot initialize checkpoint store at {self._database}"
            ) from exc

    def save(self, workflow_id: str, checkpoint: WorkflowCheckpoint) -> None:
        if checkpoint.workflow_id != workflow_id:
            raise WorkflowPersistenceError("checkpoint workflow_id does not match storage key")
        try:
            with self._connect() as connection:
                payload = checkpoint.model_dump_json()
                connection.execute(
                    """
                    INSERT INTO workflow_checkpoints(workflow_id, checkpoint_json, saved_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        checkpoint_json = excluded.checkpoint_json,
                        saved_at = excluded.saved_at
                    """,
                    (workflow_id, payload, checkpoint.saved_at.isoformat()),
                )
                connection.execute(
                    """
                    INSERT INTO workflow_history(workflow_id, checkpoint_json, saved_at)
                    VALUES (?, ?, ?)
                    """,
                    (workflow_id, payload, checkpoint.saved_at.isoformat()),
                )
        except sqlite3.Error as exc:
            raise WorkflowPersistenceError(f"cannot save workflow {workflow_id!r}") from exc

    def load(self, workflow_id: str) -> WorkflowCheckpoint | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT checkpoint_json FROM workflow_checkpoints WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise WorkflowPersistenceError(f"cannot load workflow {workflow_id!r}") from exc
        return WorkflowCheckpoint.model_validate_json(row[0]) if row is not None else None

    def list_history(self, workflow_id: str) -> list[WorkflowCheckpoint]:
        """Return append-only state transitions for audit and debugging."""

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT checkpoint_json FROM workflow_history
                    WHERE workflow_id = ? ORDER BY sequence
                    """,
                    (workflow_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise WorkflowPersistenceError(f"cannot load workflow history {workflow_id!r}") from exc
        return [WorkflowCheckpoint.model_validate_json(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database, timeout=10)
