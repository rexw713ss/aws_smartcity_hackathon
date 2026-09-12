"""SQLite-backed dataset catalog with version history and a live pointer."""

import sqlite3
from pathlib import Path

from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import CatalogOperationError, DatasetNotFoundError
from youth_compass.domain.profiles import DatasetProfile


class SQLiteCatalog:
    """Persist every dataset version and atomically advance published versions."""

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()
        try:
            self._database.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS dataset_versions (
                        dataset_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(dataset_id, version)
                    );
                    CREATE TABLE IF NOT EXISTS published_versions (
                        dataset_id TEXT PRIMARY KEY,
                        version TEXT NOT NULL,
                        FOREIGN KEY(dataset_id, version)
                            REFERENCES dataset_versions(dataset_id, version)
                    );
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise CatalogOperationError(f"cannot initialize catalog at {self._database}") from exc

    def register(self, dataset: DatasetMetadata) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO dataset_versions(dataset_id, version, metadata_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(dataset_id, version) DO UPDATE SET
                        metadata_json = excluded.metadata_json,
                        created_at = excluded.created_at
                    """,
                    (
                        dataset.dataset_id,
                        dataset.version,
                        dataset.model_dump_json(),
                        dataset.created_at.isoformat(),
                    ),
                )
                if dataset.status is DatasetStatus.PUBLISHED:
                    connection.execute(
                        """
                        INSERT INTO published_versions(dataset_id, version) VALUES (?, ?)
                        ON CONFLICT(dataset_id) DO UPDATE SET version = excluded.version
                        """,
                        (dataset.dataset_id, dataset.version),
                    )
        except sqlite3.Error as exc:
            raise CatalogOperationError(f"cannot register dataset {dataset.dataset_id!r}") from exc

    def get(self, dataset_id: str) -> DatasetMetadata:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT versions.metadata_json
                    FROM dataset_versions AS versions
                    LEFT JOIN published_versions AS published
                      ON published.dataset_id = versions.dataset_id
                     AND published.version = versions.version
                    WHERE versions.dataset_id = ?
                    ORDER BY (published.version IS NOT NULL) DESC,
                             versions.created_at DESC,
                             versions.rowid DESC
                    LIMIT 1
                    """,
                    (dataset_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise CatalogOperationError(f"cannot read dataset {dataset_id!r}") from exc
        if row is None:
            raise DatasetNotFoundError(dataset_id)
        return DatasetMetadata.model_validate_json(row[0])

    def search_compatible(self, profile: DatasetProfile) -> list[DatasetMetadata]:
        wanted = set(profile.candidate_grain)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT versions.metadata_json
                    FROM dataset_versions AS versions
                    JOIN published_versions AS published
                      ON published.dataset_id = versions.dataset_id
                     AND published.version = versions.version
                    ORDER BY versions.dataset_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise CatalogOperationError("cannot search compatible datasets") from exc
        records = [DatasetMetadata.model_validate_json(row[0]) for row in rows]
        if not wanted:
            return records
        return [record for record in records if wanted.issubset(set(record.grain.dimensions))]

    def list_versions(self, dataset_id: str) -> list[DatasetMetadata]:
        """Return audit history for local review tooling, oldest first."""

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT metadata_json FROM dataset_versions
                    WHERE dataset_id = ? ORDER BY created_at, rowid
                    """,
                    (dataset_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise CatalogOperationError(f"cannot list versions for {dataset_id!r}") from exc
        return [DatasetMetadata.model_validate_json(row[0]) for row in rows]

    def get_version(self, dataset_id: str, version: str) -> DatasetMetadata:
        """Return one immutable metadata version for API lineage views."""

        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT metadata_json FROM dataset_versions
                    WHERE dataset_id = ? AND version = ?
                    """,
                    (dataset_id, version),
                ).fetchone()
        except sqlite3.Error as exc:
            raise CatalogOperationError(
                f"cannot read dataset {dataset_id!r} version {version!r}"
            ) from exc
        if row is None:
            raise DatasetNotFoundError(f"{dataset_id}@{version}")
        return DatasetMetadata.model_validate_json(row[0])

    def list_datasets(self) -> list[DatasetMetadata]:
        """Return one visible record per dataset, preferring its published version."""

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT versions.dataset_id, versions.metadata_json,
                           (published.version IS NOT NULL) AS is_published
                    FROM dataset_versions AS versions
                    LEFT JOIN published_versions AS published
                      ON published.dataset_id = versions.dataset_id
                     AND published.version = versions.version
                    ORDER BY versions.dataset_id, is_published DESC,
                             versions.created_at DESC, versions.rowid DESC
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise CatalogOperationError("cannot list datasets") from exc
        visible: dict[str, DatasetMetadata] = {}
        for dataset_id, payload, _ in rows:
            visible.setdefault(str(dataset_id), DatasetMetadata.model_validate_json(payload))
        return list(visible.values())

    def published_version(self, dataset_id: str) -> str | None:
        """Return the live version without exposing SQLite to application code."""

        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT version FROM published_versions WHERE dataset_id = ?", (dataset_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise CatalogOperationError(
                f"cannot read published version for {dataset_id!r}"
            ) from exc
        return str(row[0]) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
