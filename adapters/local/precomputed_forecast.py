"""Read a published, precomputed annual forecast from an immutable Parquet artifact."""

from datetime import UTC, datetime, time
from pathlib import Path

import duckdb
from pydantic import ValidationError

from youth_compass.domain.errors import ForecastNotAvailableError, TrainingRejectedError
from youth_compass.ports import (
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    TrainingRequest,
    TrainingRun,
)


class PrecomputedParquetForecastService:
    """Serve the latest eligible model version without training at request time."""

    def __init__(self, artifact: Path) -> None:
        self._artifact = artifact.resolve()

    def get_forecast(self, request: ForecastRequest) -> ForecastResult:
        if not self._artifact.is_file():
            raise ForecastNotAvailableError(
                f"published forecast artifact is unavailable: {self._artifact}"
            )
        clauses = ["metric_code = ?"]
        parameters: list[object] = [str(self._artifact), request.metric_code]
        if request.district_codes:
            clauses.append(
                "district_code IN (" + ", ".join("?" for _ in request.district_codes) + ")"
            )
            parameters.extend(request.district_codes)
        if request.as_of is not None:
            clauses.append("generated_at <= ?")
            parameters.append(datetime.combine(request.as_of, time.max))

        sql = f"""
            WITH eligible AS (
                SELECT metric_code, district_code, year_gregorian, value, lower, upper,
                       model_version, generated_at
                FROM read_parquet(?)
                WHERE {" AND ".join(clauses)}
            ), latest AS (
                SELECT model_version, generated_at
                FROM eligible
                ORDER BY generated_at DESC, model_version DESC
                LIMIT 1
            ), selected AS (
                SELECT eligible.*
                FROM eligible, latest
                WHERE eligible.model_version = latest.model_version
                  AND eligible.generated_at = latest.generated_at
                  {"AND eligible.year_gregorian > ?" if request.as_of is not None else ""}
            ), forecast_years AS (
                SELECT DISTINCT year_gregorian
                FROM selected
                ORDER BY year_gregorian
                LIMIT ?
            )
            SELECT district_code, year_gregorian, value, lower, upper,
                   model_version, generated_at::TIMESTAMP AS generated_at
            FROM selected
            WHERE year_gregorian IN (SELECT year_gregorian FROM forecast_years)
            ORDER BY district_code, year_gregorian
        """
        if request.as_of is not None:
            parameters.append(request.as_of.year)
        parameters.append(request.horizon_years)
        connection = duckdb.connect(database=":memory:")
        try:
            rows = connection.execute(sql, parameters).fetchall()
        except duckdb.Error as exc:
            raise ForecastNotAvailableError(
                f"published forecast artifact is invalid: {str(exc)[:300]}"
            ) from exc
        finally:
            connection.close()
        if not rows:
            if request.district_codes:
                raise ForecastNotAvailableError(
                    "no published forecast exists for requested districts: "
                    + ", ".join(request.district_codes)
                )
            raise ForecastNotAvailableError(
                f"no published forecast exists for metric {request.metric_code!r}"
            )
        available_districts = {str(row[0]) for row in rows}
        missing_districts = sorted(set(request.district_codes) - available_districts)
        if missing_districts:
            raise ForecastNotAvailableError(
                "no published forecast exists for districts: " + ", ".join(missing_districts)
            )
        try:
            points = [
                ForecastPoint(
                    district_code=str(row[0]),
                    year_gregorian=int(row[1]),
                    value=float(row[2]),
                    lower=float(row[3]),
                    upper=float(row[4]),
                )
                for row in rows
            ]
            generated_at = rows[0][6]
            if not isinstance(generated_at, datetime):
                raise TypeError("generated_at is not a timestamp")
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=UTC)
            return ForecastResult(
                metric_code=request.metric_code,
                model_version=str(rows[0][5]),
                points=points,
                generated_at=generated_at,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ForecastNotAvailableError(
                "published forecast artifact contains invalid values"
            ) from exc

    def trigger_training(self, request: TrainingRequest) -> TrainingRun:
        del request
        raise TrainingRejectedError(
            "precomputed forecast adapter is read-only; run the offline forecast pipeline"
        )
