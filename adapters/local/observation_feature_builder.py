"""Build district features from canonical-observation Parquet with DuckDB."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from youth_compass.decisioning import (
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
    NewTaipeiDistrictResolver,
    ObservationFeatureBuildSpec,
)
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import QueryExecutionError

_AGGREGATION_SQL = {
    "sum": "SUM",
    "mean": "AVG",
    "median": "MEDIAN",
    "min": "MIN",
    "max": "MAX",
}


class FeatureBuildError(ValueError):
    """Canonical observations cannot satisfy a registered feature contract."""


class CanonicalObservationFeatureBuilder:
    """Aggregate a published canonical metric into evidence-carrying district features."""

    def __init__(
        self,
        registry: FeatureRegistry,
        resolver: NewTaipeiDistrictResolver | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or NewTaipeiDistrictResolver()

    def build(
        self,
        parquet: Path,
        metadata: DatasetMetadata,
        spec: ObservationFeatureBuildSpec,
    ) -> tuple[FeatureValue, ...]:
        source = parquet.resolve()
        if not source.is_file():
            raise FeatureBuildError(f"canonical observation file is unavailable: {source}")
        if metadata.status is not DatasetStatus.PUBLISHED:
            raise FeatureBuildError("features may only be built from a published dataset version")
        definition = self._registry.get(spec.feature_code)
        if spec.source_metric_code not in definition.source_metric_codes:
            raise FeatureBuildError(
                f"metric {spec.source_metric_code!r} is not declared by feature "
                f"{spec.feature_code!r}"
            )
        if definition.aggregation_method != spec.aggregation.value:
            raise FeatureBuildError(
                f"feature {spec.feature_code!r} requires aggregation "
                f"{definition.aggregation_method!r}, got {spec.aggregation.value!r}"
            )

        connection = duckdb.connect(database=":memory:")
        try:
            self._validate_lineage(connection, source, metadata, spec.source_metric_code)
            year, month = self._resolve_period(connection, source, spec)
            rows = self._aggregate(connection, source, spec, year, month)
        except duckdb.Error as exc:
            raise QueryExecutionError(f"DuckDB feature build failed: {str(exc)[:300]}") from exc
        finally:
            connection.close()
        if not rows:
            raise FeatureBuildError(f"no observations found for metric {spec.source_metric_code!r}")

        evidence = FeatureEvidence(
            dataset_id=metadata.dataset_id,
            dataset_version=metadata.version,
            source_uri=metadata.source_uri,
            quality_score=metadata.quality_score,
            retrieved_at=metadata.published_at or metadata.created_at,
        )
        observed_at = datetime(year, month or 1, 1, tzinfo=UTC)
        values: list[FeatureValue] = []
        for district_code, value, unit_count, unit_code, scope_count in rows:
            if int(unit_count) != 1:
                raise FeatureBuildError(f"district {district_code!r} contains mixed units")
            if int(scope_count) != 1:
                raise FeatureBuildError(
                    f"district {district_code!r} contains mixed population scopes"
                )
            if str(unit_code) != definition.unit_code:
                raise FeatureBuildError(
                    f"feature {spec.feature_code!r} expects unit {definition.unit_code!r}, "
                    f"got {unit_code!r}"
                )
            resolution = self._resolver.resolve(district_code)
            if resolution.location is None:
                raise FeatureBuildError(f"district {district_code!r} cannot be resolved")
            values.append(
                FeatureValue(
                    entity_id=resolution.location.location_id,
                    feature_code=spec.feature_code,
                    feature_version=definition.version,
                    value=float(value),
                    observed_at=observed_at,
                    evidence=(evidence,),
                )
            )
        return tuple(values)

    @staticmethod
    def _validate_lineage(
        connection: duckdb.DuckDBPyConnection,
        source: Path,
        metadata: DatasetMetadata,
        metric_code: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT dataset_id), MIN(dataset_id),
                   COUNT(DISTINCT dataset_version), MIN(dataset_version)
            FROM read_parquet(?)
            WHERE metric_code = ?
            """,
            [str(source), metric_code],
        ).fetchone()
        if row is None or int(row[0]) != 1 or int(row[2]) != 1:
            raise FeatureBuildError("source observations do not have unique dataset lineage")
        if str(row[1]) != metadata.dataset_id or str(row[3]) != metadata.version:
            raise FeatureBuildError("source observation lineage does not match catalog metadata")

    @staticmethod
    def _resolve_period(
        connection: duckdb.DuckDBPyConnection,
        source: Path,
        spec: ObservationFeatureBuildSpec,
    ) -> tuple[int, int | None]:
        if spec.year_gregorian is not None:
            return spec.year_gregorian, spec.month
        row = connection.execute(
            """
            SELECT year_gregorian, month
            FROM read_parquet(?)
            WHERE metric_code = ? AND year_gregorian IS NOT NULL
            GROUP BY year_gregorian, month
            ORDER BY year_gregorian DESC, month DESC NULLS LAST
            LIMIT 1
            """,
            [str(source), spec.source_metric_code],
        ).fetchone()
        if row is None:
            raise FeatureBuildError(
                f"metric {spec.source_metric_code!r} has no resolvable observation period"
            )
        return int(row[0]), int(row[1]) if row[1] is not None else None

    @staticmethod
    def _aggregate(
        connection: duckdb.DuckDBPyConnection,
        source: Path,
        spec: ObservationFeatureBuildSpec,
        year: int,
        month: int | None,
    ) -> list[tuple[object, ...]]:
        aggregate = _AGGREGATION_SQL[spec.aggregation.value]
        month_clause = "month IS NULL" if month is None else "month = ?"
        parameters: list[object] = [str(source), spec.source_metric_code, year]
        if month is not None:
            parameters.append(month)
        return connection.execute(
            f"""
            SELECT district_code,
                   {aggregate}(metric_value) AS feature_value,
                   COUNT(DISTINCT unit_code) AS unit_count,
                   MIN(unit_code) AS unit_code,
                   COUNT(DISTINCT population_scope) AS scope_count
            FROM read_parquet(?)
            WHERE metric_code = ?
              AND year_gregorian = ?
              AND {month_clause}
              AND district_code IS NOT NULL
            GROUP BY district_code
            ORDER BY district_code
            """,
            parameters,
        ).fetchall()
