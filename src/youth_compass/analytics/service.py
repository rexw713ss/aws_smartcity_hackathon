"""Deterministic aggregations for dashboard and future agent tools."""

import re

from pydantic import BaseModel, Field

from youth_compass.domain.contracts import DatasetMetadata
from youth_compass.domain.errors import AnalyticsNotAvailableError, QueryExecutionError
from youth_compass.ports import QueryEngine, QuerySpec

_PERIOD = re.compile(r"^(?P<year>\d{4})(?:-(?P<month>0[1-9]|1[0-2]))?$")
_DIMENSIONS = [
    "year_gregorian",
    "month",
    "district_code",
    "district_name",
    "metric_code",
    "unit_code",
    "population_scope",
    "is_estimated",
]


class CitySummary(BaseModel):
    dataset_id: str
    dataset_version: str
    metric_code: str
    period: str
    value: float
    unit_code: str
    population_scope: str
    district_count: int = Field(ge=0)
    estimated_value: float = Field(ge=0)
    quality_score: float = Field(ge=0, le=1)


class DistrictMetric(BaseModel):
    district_code: str
    district_name: str | None = None
    value: float
    estimated_value: float = Field(ge=0)


class DistrictProfile(BaseModel):
    dataset_id: str
    dataset_version: str
    metric_code: str
    period: str
    unit_code: str
    population_scope: str
    quality_score: float = Field(ge=0, le=1)
    districts: list[DistrictMetric]


class CuratedAnalyticsService:
    """Read one published canonical table through an allowlisted QueryEngine."""

    def __init__(self, query_engine: QueryEngine, metadata: DatasetMetadata) -> None:
        self._query = query_engine
        self._metadata = metadata

    def city_summary(self, metric_code: str, period: str | None = None) -> CitySummary:
        records, resolved_period = self._records(metric_code, period)
        unit, scope = _consistent_context(records)
        values = [_number(record["metric_value"]) for record in records]
        estimated = sum(
            value
            for value, record in zip(values, records, strict=True)
            if record["is_estimated"] is True
        )
        return CitySummary(
            dataset_id=self._metadata.dataset_id,
            dataset_version=self._metadata.version,
            metric_code=metric_code,
            period=resolved_period,
            value=round(sum(values), 4),
            unit_code=unit,
            population_scope=scope,
            district_count=len(
                {str(record["district_code"]) for record in records if record["district_code"]}
            ),
            estimated_value=round(estimated, 4),
            quality_score=self._metadata.quality_score,
        )

    def district_profile(
        self,
        metric_code: str,
        *,
        district_codes: list[str] | None = None,
        period: str | None = None,
    ) -> DistrictProfile:
        records, resolved_period = self._records(metric_code, period)
        requested = set(district_codes or [])
        if requested:
            records = [record for record in records if record["district_code"] in requested]
        grouped: dict[str, DistrictMetric] = {}
        for record in records:
            code = str(record["district_code"] or "")
            if not code:
                continue
            value = _number(record["metric_value"])
            current = grouped.get(code)
            if current is None:
                current = DistrictMetric(
                    district_code=code,
                    district_name=(
                        str(record["district_name"]) if record["district_name"] else None
                    ),
                    value=0,
                    estimated_value=0,
                )
                grouped[code] = current
            current.value = round(current.value + value, 4)
            if record["is_estimated"] is True:
                current.estimated_value = round(current.estimated_value + value, 4)
        if requested - set(grouped):
            missing = ", ".join(sorted(requested - set(grouped)))
            raise AnalyticsNotAvailableError(f"no observations for district codes: {missing}")
        unit, scope = _consistent_context(records)
        return DistrictProfile(
            dataset_id=self._metadata.dataset_id,
            dataset_version=self._metadata.version,
            metric_code=metric_code,
            period=resolved_period,
            unit_code=unit,
            population_scope=scope,
            quality_score=self._metadata.quality_score,
            districts=[grouped[code] for code in sorted(grouped)],
        )

    def _records(self, metric_code: str, period: str | None) -> tuple[list[dict[str, object]], str]:
        filters: dict[str, str | int | float | bool] = {"metric_code": metric_code}
        requested_period = _parse_period(period) if period else None
        if requested_period:
            filters["year_gregorian"] = requested_period[0]
            if requested_period[1] is not None:
                filters["month"] = requested_period[1]
        result = self._query.execute(
            QuerySpec(
                table=self._metadata.dataset_id,
                dimensions=_DIMENSIONS,
                metrics=["metric_value"],
                filters=filters,
                max_rows=100_000,
            )
        )
        if result.truncated:
            raise QueryExecutionError("analytics input exceeded the safe 100000-row query limit")
        records: list[dict[str, object]] = [
            dict(zip(result.columns, row, strict=True)) for row in result.rows
        ]
        if not records:
            raise AnalyticsNotAvailableError(
                f"no observations for metric {metric_code!r} and period {period!r}"
            )
        if requested_period:
            resolved = _format_period(*requested_period)
            return records, resolved
        periods = [
            (_integer(record["year_gregorian"]), _optional_integer(record["month"]))
            for record in records
        ]
        latest = max(periods, key=lambda value: (value[0], value[1] or 0))
        latest_records = [
            record
            for record in records
            if (
                _integer(record["year_gregorian"]),
                _optional_integer(record["month"]),
            )
            == latest
        ]
        return latest_records, _format_period(*latest)


def _parse_period(period: str) -> tuple[int, int | None]:
    match = _PERIOD.fullmatch(period)
    if match is None:
        raise AnalyticsNotAvailableError("period must use YYYY or YYYY-MM")
    month = match.group("month")
    return int(match.group("year")), int(month) if month else None


def _format_period(year: int, month: int | None) -> str:
    return f"{year:04d}-{month:02d}" if month else f"{year:04d}"


def _consistent_context(records: list[dict[str, object]]) -> tuple[str, str]:
    if not records:
        raise AnalyticsNotAvailableError("no observations match the requested districts")
    units = {str(record["unit_code"]) for record in records}
    scopes = {str(record["population_scope"]) for record in records}
    if len(units) != 1 or len(scopes) != 1:
        raise QueryExecutionError("mixed units or population scopes cannot be aggregated")
    return next(iter(units)), next(iter(scopes))


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise QueryExecutionError("metric_value is not numeric")
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryExecutionError("year_gregorian is not an integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)
