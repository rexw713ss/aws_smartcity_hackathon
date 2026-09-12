"""Local Parquet materialization and DuckDB retrieval for reusable features."""

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import TypeAdapter, ValidationError

from youth_compass.decisioning import FeatureEvidence, FeatureRegistry, FeatureValue
from youth_compass.decisioning.provider import FeatureProvider, FeatureQuery, FeatureSet
from youth_compass.decisioning.schema import FEATURE_VALUE_SCHEMA
from youth_compass.domain.errors import QueryExecutionError

_EVIDENCE_ADAPTER = TypeAdapter(tuple[FeatureEvidence, ...])


class FeatureMaterializationConflictError(ValueError):
    """A caller attempted to overwrite an immutable feature materialization."""


class FeatureParquetMaterializer:
    """Validate and atomically write an immutable reusable-feature snapshot."""

    def __init__(self, registry: FeatureRegistry) -> None:
        self._registry = registry

    def materialize(self, values: Iterable[FeatureValue], destination: Path) -> Path:
        records = list(values)
        if not records:
            raise ValueError("at least one feature value is required")
        keys = [
            (value.entity_id, value.feature_code, value.feature_version, value.observed_at)
            for value in records
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("feature entity, code, and observed_at keys must be unique")
        rows = [self._row(value) for value in records]

        final = destination.resolve()
        if final.exists():
            raise FeatureMaterializationConflictError(
                f"immutable feature materialization already exists: {final}"
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{final.name}.", suffix=".tmp", dir=final.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            table = pa.Table.from_pylist(rows, schema=FEATURE_VALUE_SCHEMA)
            pq.write_table(table, temporary, compression="zstd")
            written = pq.ParquetFile(temporary)
            if not written.schema_arrow.equals(FEATURE_VALUE_SCHEMA):
                raise QueryExecutionError("feature Parquet schema verification failed")
            if written.metadata.num_rows != len(records):
                raise QueryExecutionError("feature Parquet row-count verification failed")
            os.replace(temporary, final)
            return final
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _row(self, value: FeatureValue) -> dict[str, object]:
        definition = self._registry.get(value.feature_code, value.feature_version)
        if definition.valid_min is not None and value.value < definition.valid_min:
            raise ValueError(f"{definition.feature_code} is below its valid minimum")
        if definition.valid_max is not None and value.value > definition.valid_max:
            raise ValueError(f"{definition.feature_code} exceeds its valid maximum")
        quality_score = min(item.quality_score for item in value.evidence)
        latest_retrieved_at = max(item.retrieved_at for item in value.evidence)
        evidence_json = json.dumps(
            [item.model_dump(mode="json") for item in value.evidence],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "entity_id": value.entity_id,
            "feature_code": value.feature_code,
            "feature_version": value.feature_version,
            "feature_value": value.value,
            "observed_at": _utc_naive(value.observed_at),
            "quality_score": quality_score,
            "latest_retrieved_at": _utc_naive(latest_retrieved_at),
            "evidence_json": evidence_json,
        }


class DuckDBFeatureProvider(FeatureProvider):
    """Read latest feature values from a trusted immutable Parquet snapshot."""

    def __init__(self, parquet: Path, registry: FeatureRegistry) -> None:
        self._parquet = parquet.resolve()
        self._registry = registry

    def get_features(self, query: FeatureQuery) -> FeatureSet:
        if not self._parquet.is_file():
            raise QueryExecutionError(f"feature materialization is unavailable: {self._parquet}")
        requested_versions = {
            feature_code: self._registry.get(
                feature_code, query.feature_versions.get(feature_code)
            ).version
            for feature_code in query.feature_codes
        }

        clauses = [
            "("
            + " OR ".join("(feature_code = ? AND feature_version = ?)" for _ in requested_versions)
            + ")",
            "quality_score >= ?",
        ]
        parameters: list[object] = [str(self._parquet)]
        for feature_code, version in requested_versions.items():
            parameters.extend((feature_code, version))
        parameters.append(query.min_quality_score)
        if query.entity_ids:
            clauses.append(f"entity_id IN ({_placeholders(len(query.entity_ids))})")
            parameters.extend(query.entity_ids)
        if query.as_of is not None:
            clauses.append("(observed_at IS NULL OR observed_at <= ?)")
            parameters.append(_utc_naive(query.as_of))
        parameters.append(query.max_values + 1)

        sql = f"""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY entity_id, feature_code, feature_version
                    ORDER BY observed_at DESC NULLS LAST, latest_retrieved_at DESC
                ) AS recency_rank
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
            )
            SELECT entity_id, feature_code, feature_version,
                   feature_value, observed_at, evidence_json
            FROM ranked
            WHERE recency_rank = 1
            ORDER BY entity_id, feature_code
            LIMIT ?
        """
        connection = duckdb.connect(database=":memory:")
        try:
            rows = connection.execute(sql, parameters).fetchall()
        except duckdb.Error as exc:
            raise QueryExecutionError(f"DuckDB feature query failed: {str(exc)[:300]}") from exc
        finally:
            connection.close()

        truncated = len(rows) > query.max_values
        try:
            values = tuple(
                FeatureValue(
                    entity_id=str(row[0]),
                    feature_code=str(row[1]),
                    feature_version=str(row[2]),
                    value=float(row[3]),
                    observed_at=(row[4].replace(tzinfo=UTC) if row[4] is not None else None),
                    evidence=_EVIDENCE_ADAPTER.validate_json(str(row[5])),
                )
                for row in rows[: query.max_values]
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise QueryExecutionError("feature materialization contains invalid values") from exc
        return FeatureSet(values=values, truncated=truncated)


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None)
