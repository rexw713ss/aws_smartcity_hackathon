"""Read a published, precomputed annual forecast from an immutable Parquet artifact."""

import json
from datetime import UTC, datetime, time
from pathlib import Path

import duckdb
from pydantic import ValidationError

from youth_compass.domain.errors import ForecastNotAvailableError, TrainingRejectedError
from youth_compass.ontology import district_spellings, resolve_district_name
from youth_compass.ports import (
    ForecastComponents,
    ForecastEvaluation,
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    TrainingRequest,
    TrainingRun,
)

# Optional artifact columns: a cohort forecast explains each point with these.
_COMPONENT_COLUMNS = ("base_period", "base_value", "entering", "ageing_out", "net_change")


class PrecomputedParquetForecastService:
    """Serve the latest eligible model version without training at request time."""

    def __init__(self, artifact: Path, *, model_card: Path | None = None) -> None:
        self._artifact = artifact.resolve()
        # The card sits beside the artifact unless a caller stages both elsewhere.
        self._model_card = (model_card or artifact.with_name("model-card.json")).resolve()

    def get_forecast(self, request: ForecastRequest) -> ForecastResult:
        if not self._artifact.is_file():
            raise ForecastNotAvailableError(
                f"published forecast artifact is unavailable: {self._artifact}"
            )
        clauses = ["metric_code = ?"]
        parameters: list[object] = [str(self._artifact), request.metric_code]
        # A published artifact may key districts by canonical code or by the
        # identifier its source used, and a caller may ask in Chinese, English,
        # or Vietnamese. Widen the filter to every spelling of the same
        # district; completeness is still judged per requested district below.
        requested = _district_filter(request.district_codes)
        if requested:
            clauses.append("district_code IN (" + ", ".join("?" for _ in requested) + ")")
            parameters.extend(requested)
        if request.as_of is not None:
            clauses.append("generated_at <= ?")
            parameters.append(datetime.combine(request.as_of, time.max))

        optional = self._optional_columns()
        extra = "".join(f", {column}" for column in optional)
        sql = f"""
            WITH eligible AS (
                SELECT metric_code, district_code, year_gregorian, value, lower, upper,
                       model_version, generated_at{extra}
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
                   model_version, generated_at::TIMESTAMP AS generated_at{extra}
            FROM selected
            WHERE year_gregorian IN (SELECT year_gregorian FROM forecast_years)
            ORDER BY district_code, year_gregorian
        """
        if request.as_of is not None:
            parameters.append(request.as_of.year)
        parameters.append(request.horizon_years)
        connection = duckdb.connect(database=":memory:")
        try:
            # Casting a TIMESTAMPTZ to TIMESTAMP uses the session time zone, which
            # defaults to the host's. Pin it so the naive result is UTC, as the
            # code below assumes, and so `as_of` compares in UTC too.
            connection.execute("SET TimeZone = 'UTC'")
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
        available_districts = {_district_key(str(row[0])) for row in rows}
        missing_districts = sorted(
            code
            for code in request.district_codes
            if _district_key(code) not in available_districts
        )
        if missing_districts:
            raise ForecastNotAvailableError(
                "no published forecast exists for districts: " + ", ".join(missing_districts)
            )
        try:
            points = [_point(row, optional) for row in rows]
            generated_at = rows[0][6]
            if not isinstance(generated_at, datetime):
                raise TypeError("generated_at is not a timestamp")
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=UTC)
            model_version = str(rows[0][5])
            return ForecastResult(
                metric_code=request.metric_code,
                model_version=model_version,
                points=points,
                generated_at=generated_at,
                evaluation=self._evaluation(model_version, generated_at),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ForecastNotAvailableError(
                "published forecast artifact contains invalid values"
            ) from exc

    def _optional_columns(self) -> tuple[str, ...]:
        """Explanatory columns this artifact carries, in a fixed order."""

        connection = duckdb.connect(database=":memory:")
        try:
            described = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(self._artifact)]
            ).fetchall()
        except duckdb.Error as exc:
            raise ForecastNotAvailableError(
                f"published forecast artifact is invalid: {str(exc)[:300]}"
            ) from exc
        finally:
            connection.close()
        present = {str(row[0]) for row in described}
        columns: tuple[str, ...] = ()
        if all(column in present for column in _COMPONENT_COLUMNS):
            columns += _COMPONENT_COLUMNS
        if "size_class" in present:
            columns += ("size_class",)
        return columns

    def _evaluation(self, model_version: str, generated_at: datetime) -> ForecastEvaluation | None:
        """The model card's evidence, only when it describes this exact artifact.

        A card from another run would attach evidence to numbers it was not
        computed for, so a mismatched or unreadable card is omitted rather than
        trusted; the forecast itself remains valid without it.
        """

        try:
            card = json.loads(self._model_card.read_text(encoding="utf-8"))
            card_generated = datetime.fromisoformat(str(card["generated_at"]))
            if card_generated.tzinfo is None:
                card_generated = card_generated.replace(tzinfo=UTC)
            if card["model_version"] != model_version or card_generated != generated_at:
                return None
            return ForecastEvaluation.model_validate(card["evaluation"])
        except (OSError, KeyError, TypeError, ValueError, ValidationError):
            return None

    def trigger_training(self, request: TrainingRequest) -> TrainingRun:
        del request
        raise TrainingRejectedError(
            "precomputed forecast adapter is read-only; run the offline forecast pipeline"
        )


def _point(row: tuple[object, ...], optional: tuple[str, ...]) -> ForecastPoint:
    extra = dict(zip(optional, row[7:], strict=True))
    components = None
    if all(extra.get(column) is not None for column in _COMPONENT_COLUMNS):
        components = ForecastComponents(
            base_period=str(extra["base_period"]),
            base_value=float(extra["base_value"]),  # type: ignore[arg-type]
            entering=float(extra["entering"]),  # type: ignore[arg-type]
            ageing_out=float(extra["ageing_out"]),  # type: ignore[arg-type]
            net_change=float(extra["net_change"]),  # type: ignore[arg-type]
        )
    size_class = extra.get("size_class")
    return ForecastPoint(
        district_code=str(row[0]),
        year_gregorian=int(row[1]),  # type: ignore[call-overload]
        value=float(row[2]),  # type: ignore[arg-type]
        lower=float(row[3]),  # type: ignore[arg-type]
        upper=float(row[4]),  # type: ignore[arg-type]
        components=components,
        small_area=None if size_class is None else size_class == "small",
    )


def _district_key(value: str) -> str:
    """Collapse every spelling of one district onto a single comparison key."""

    district = resolve_district_name(value).district
    return district.code if district is not None else value.casefold()


def _district_filter(district_codes: list[str]) -> list[str]:
    """Expand each requested district to every identifier that may denote it."""

    expanded: dict[str, None] = {}
    for code in district_codes:
        for spelling in district_spellings(code):
            expanded[spelling] = None
    return list(expanded)
