"""SQLite semantic catalog for reusable feature materializations."""

import sqlite3
from pathlib import Path

from youth_compass.decisioning.catalog import (
    FeatureCatalogEntry,
    FeatureMaterializationMetadata,
    FeatureMaterializationStatus,
    FeatureSearchQuery,
    SemanticFeatureCatalog,
)
from youth_compass.decisioning.registry import FeatureRegistry
from youth_compass.domain.errors import CatalogOperationError


class FeatureCatalogNotFoundError(KeyError):
    """No requested feature materialization exists in the semantic catalog."""


class FeatureCatalogConflictError(ValueError):
    """An immutable catalog identity was reused with different metadata."""


class SQLiteFeatureCatalog(SemanticFeatureCatalog):
    """Persist immutable feature metadata and one published pointer per feature."""

    def __init__(self, database: Path, registry: FeatureRegistry) -> None:
        self._database = database.resolve()
        self._registry = registry
        try:
            self._database.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS feature_materializations (
                        feature_code TEXT NOT NULL,
                        materialization_version TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        materialized_at TEXT NOT NULL,
                        PRIMARY KEY(feature_code, materialization_version)
                    );
                    CREATE TABLE IF NOT EXISTS published_feature_versions (
                        feature_code TEXT PRIMARY KEY,
                        materialization_version TEXT NOT NULL,
                        FOREIGN KEY(feature_code, materialization_version)
                            REFERENCES feature_materializations(
                                feature_code, materialization_version
                            )
                    );
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise CatalogOperationError(
                f"cannot initialize feature catalog at {self._database}"
            ) from exc

    def register(self, materialization: FeatureMaterializationMetadata) -> None:
        definition = self._registry.get(
            materialization.feature_code, materialization.feature_version
        )
        if materialization.spatial_grain != definition.spatial_grain:
            raise FeatureCatalogConflictError("materialization spatial grain mismatches feature")
        if materialization.temporal_grain != definition.temporal_grain:
            raise FeatureCatalogConflictError("materialization temporal grain mismatches feature")
        payload = materialization.model_dump_json()
        try:
            with self._connect() as connection:
                existing = connection.execute(
                    """
                    SELECT metadata_json FROM feature_materializations
                    WHERE feature_code = ? AND materialization_version = ?
                    """,
                    (materialization.feature_code, materialization.materialization_version),
                ).fetchone()
                if existing is not None and str(existing[0]) != payload:
                    raise FeatureCatalogConflictError(
                        "immutable feature materialization metadata conflicts with existing version"
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO feature_materializations(
                        feature_code, materialization_version, metadata_json, materialized_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        materialization.feature_code,
                        materialization.materialization_version,
                        payload,
                        materialization.materialized_at.isoformat(),
                    ),
                )
                if materialization.status is FeatureMaterializationStatus.PUBLISHED:
                    connection.execute(
                        """
                        INSERT INTO published_feature_versions(
                            feature_code, materialization_version
                        ) VALUES (?, ?)
                        ON CONFLICT(feature_code) DO UPDATE SET
                            materialization_version = excluded.materialization_version
                        """,
                        (materialization.feature_code, materialization.materialization_version),
                    )
        except FeatureCatalogConflictError:
            raise
        except sqlite3.Error as exc:
            raise CatalogOperationError(
                f"cannot register feature {materialization.feature_code!r}"
            ) from exc

    def get(
        self, feature_code: str, materialization_version: str | None = None
    ) -> FeatureCatalogEntry:
        try:
            with self._connect() as connection:
                if materialization_version is None:
                    row = connection.execute(
                        """
                        SELECT materializations.metadata_json
                        FROM feature_materializations AS materializations
                        JOIN published_feature_versions AS published
                          ON published.feature_code = materializations.feature_code
                         AND published.materialization_version =
                             materializations.materialization_version
                        WHERE materializations.feature_code = ?
                        """,
                        (feature_code,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        SELECT metadata_json FROM feature_materializations
                        WHERE feature_code = ? AND materialization_version = ?
                        """,
                        (feature_code, materialization_version),
                    ).fetchone()
        except sqlite3.Error as exc:
            raise CatalogOperationError(f"cannot read feature {feature_code!r}") from exc
        if row is None:
            suffix = f"@{materialization_version}" if materialization_version else ""
            raise FeatureCatalogNotFoundError(
                f"unknown feature materialization {feature_code}{suffix}"
            )
        materialization = FeatureMaterializationMetadata.model_validate_json(str(row[0]))
        definition = self._registry.get(feature_code, materialization.feature_version)
        return FeatureCatalogEntry(definition=definition, materialization=materialization)

    def search(self, query: FeatureSearchQuery) -> tuple[FeatureCatalogEntry, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT materializations.metadata_json
                    FROM feature_materializations AS materializations
                    JOIN published_feature_versions AS published
                      ON published.feature_code = materializations.feature_code
                     AND published.materialization_version =
                         materializations.materialization_version
                    ORDER BY materializations.feature_code
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise CatalogOperationError("cannot search feature catalog") from exc
        entries = []
        for row in rows:
            materialization = FeatureMaterializationMetadata.model_validate_json(str(row[0]))
            definition = self._registry.get(
                materialization.feature_code, materialization.feature_version
            )
            entry = FeatureCatalogEntry(definition=definition, materialization=materialization)
            if _matches(entry, query):
                entries.append(entry)
        return tuple(entries)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _matches(entry: FeatureCatalogEntry, query: FeatureSearchQuery) -> bool:
    definition = entry.definition
    materialization = entry.materialization
    if query.feature_codes and definition.feature_code not in query.feature_codes:
        return False
    if query.entity_type is not None and definition.entity_type is not query.entity_type:
        return False
    if query.spatial_grains and materialization.spatial_grain not in query.spatial_grains:
        return False
    if query.temporal_grains and materialization.temporal_grain not in query.temporal_grains:
        return False
    if materialization.quality_score < query.min_quality_score:
        return False
    if not set(query.required_filters).issubset(materialization.supported_filters):
        return False
    if query.observed_at is not None and (
        materialization.observed_from is None or materialization.observed_to is None
    ):
        return False
    if (
        query.observed_at is not None
        and materialization.observed_from is not None
        and query.observed_at < materialization.observed_from
    ):
        return False
    if (
        query.observed_at is not None
        and materialization.observed_to is not None
        and query.observed_at > materialization.observed_to
    ):
        return False
    if query.fresh_at is not None and (
        materialization.fresh_until is None or query.fresh_at > materialization.fresh_until
    ):
        return False
    if query.text:
        haystack = " ".join(
            (
                definition.feature_code,
                definition.display_name,
                definition.description,
                *definition.tags,
                *definition.source_metric_codes,
                *definition.source_feature_codes,
            )
        ).casefold()
        if not all(token in haystack for token in query.text.casefold().split()):
            return False
    return True
