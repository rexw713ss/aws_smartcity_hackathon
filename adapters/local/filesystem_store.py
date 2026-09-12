"""Filesystem-backed ObjectStore with a SQLite key index."""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

from youth_compass.domain.errors import ObjectNotFoundError, ObjectStoreOperationError

_SCHEME = "fileobj://"


class FileSystemObjectStore:
    """Store immutable-addressed blobs locally while preserving arbitrary keys."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._objects = self._root / "objects"
        self._database = self._root / "index.sqlite3"
        try:
            self._objects.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS objects (
                        object_key TEXT PRIMARY KEY,
                        blob_name TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise ObjectStoreOperationError(
                f"cannot initialize object store at {self._root}"
            ) from exc

    def put(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        normalized = self._validate_key(key)
        blob_name = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        stored_metadata = {**metadata, "sha256": hashlib.sha256(content).hexdigest()}
        destination = self._objects / blob_name
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self._objects, delete=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, destination)
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO objects(object_key, blob_name, metadata_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(object_key) DO UPDATE SET
                        blob_name = excluded.blob_name,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        normalized,
                        blob_name,
                        json.dumps(stored_metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
        except (OSError, sqlite3.Error) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ObjectStoreOperationError(f"cannot write object {normalized!r}") from exc
        return f"{_SCHEME}{quote(normalized, safe='/')}"

    def get(self, uri: str) -> bytes:
        key = self._key(uri)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT blob_name, metadata_json FROM objects WHERE object_key = ?", (key,)
                ).fetchone()
            if row is None:
                raise ObjectNotFoundError(uri)
            content = (self._objects / str(row[0])).read_bytes()
            expected = json.loads(str(row[1])).get("sha256")
            if expected != hashlib.sha256(content).hexdigest():
                raise ObjectStoreOperationError(f"checksum mismatch for object {key!r}")
            return content
        except ObjectNotFoundError:
            raise
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(uri) from exc
        except (OSError, sqlite3.Error) as exc:
            raise ObjectStoreOperationError(f"cannot read object {key!r}") from exc

    def list(self, prefix: str) -> list[str]:
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT object_key FROM objects").fetchall()
        except sqlite3.Error as exc:
            raise ObjectStoreOperationError(f"cannot list objects under {prefix!r}") from exc
        return sorted(str(row[0]) for row in rows if str(row[0]).startswith(prefix))

    def exists(self, uri: str) -> bool:
        key = self._key(uri)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT blob_name FROM objects WHERE object_key = ?", (key,)
                ).fetchone()
            return row is not None and (self._objects / str(row[0])).is_file()
        except (OSError, sqlite3.Error) as exc:
            raise ObjectStoreOperationError(f"cannot check object {key!r}") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database, timeout=10)

    @staticmethod
    def _validate_key(key: str) -> str:
        if not key or "\x00" in key:
            raise ObjectStoreOperationError("object key must be non-empty and contain no NUL")
        return key

    @classmethod
    def _key(cls, uri: str) -> str:
        return unquote(uri[len(_SCHEME) :]) if uri.startswith(_SCHEME) else uri
