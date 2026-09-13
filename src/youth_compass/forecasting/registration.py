"""Read same-month annual snapshots of single-year ages from the registration source.

The cohort forecast and the What-if scenario both start from this one reader, so
they share the snapshot month, the district identity, and the years a ratio may
use, and therefore agree on the baseline they report.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from youth_compass.forecasting.cohort import YOUTH_MAX_AGE, youth_count

DISTRICT_COUNT = 29
# The compact Parquet extract a deployment packages in place of the CSV.
REGISTRATION_EXTRACT_NAME = "registration.parquet"


class RegistrationSourceError(ValueError):
    """The registration source cannot provide complete district snapshots."""


@dataclass(frozen=True, slots=True)
class RegistrationHistory:
    """Snapshots of ages 0-35 in one calendar month, for every complete year."""

    month: int
    snapshots: dict[int, dict[str, dict[int, float]]]
    # year -> district code -> registered persons of every age
    totals: dict[int, dict[str, float]]

    @property
    def base_year(self) -> int:
        return max(self.snapshots)

    @property
    def base_period(self) -> str:
        return f"{self.base_year:04d}-{self.month:02d}"

    @property
    def districts(self) -> list[str]:
        return sorted(self.snapshots[self.base_year])

    def youth(self, year: int, district: str) -> float | None:
        ages = self.snapshots.get(year, {}).get(district)
        return youth_count(ages) if ages is not None else None


def load_registration_history(source: Path) -> RegistrationHistory:
    """Snapshots for the latest month in which every district reports ages 0-35.

    Every year uses that same month, so annual change is never confused with
    seasonality. Years missing any district or age for the month are left out
    rather than imputed.

    Raises:
        RegistrationSourceError: the file is unreadable or has no complete month.
    """

    reader = _reader(source)
    connection = duckdb.connect(database=":memory:")
    try:
        latest = connection.execute(
            f"""
            SELECT "民國年"::INTEGER AS year_roc, "月"::INTEGER AS month
            FROM {reader}
            WHERE "年齡下限" = "年齡上限" AND "年齡下限" BETWEEN 0 AND ?
            GROUP BY 1, 2
            HAVING count(DISTINCT "區代碼") = ?
               AND count(DISTINCT ("區代碼", "年齡下限")) = ?
            ORDER BY 1 DESC, 2 DESC
            LIMIT 1
            """,
            [str(source), YOUTH_MAX_AGE, DISTRICT_COUNT, DISTRICT_COUNT * (YOUTH_MAX_AGE + 1)],
        ).fetchone()
        if latest is None:
            raise RegistrationSourceError(
                "the source has no month covering every district and ages 0-35"
            )
        month = int(latest[1])
        rows = connection.execute(
            f"""
            SELECT "民國年"::INTEGER + 1911,
                   lpad(CAST("區代碼" AS VARCHAR), 2, '0'),
                   "年齡下限"::INTEGER,
                   SUM("人數")::DOUBLE
            FROM {reader}
            WHERE "月" = ? AND "年齡下限" = "年齡上限"
            GROUP BY 1, 2, 3
            """,
            [str(source), month],
        ).fetchall()
    except duckdb.Error as exc:
        raise RegistrationSourceError(
            f"the registration source could not be read: {str(exc)[:240]}"
        ) from exc
    finally:
        connection.close()

    ages_by_year: dict[int, dict[str, dict[int, float]]] = {}
    totals: dict[int, dict[str, float]] = {}
    for year, code, age, count in rows:
        by_district = totals.setdefault(int(year), {})
        by_district[str(code)] = by_district.get(str(code), 0.0) + float(count)
        if int(age) <= YOUTH_MAX_AGE:
            ages_by_year.setdefault(int(year), {}).setdefault(str(code), {})[int(age)] = float(
                count
            )
    complete = {
        year: districts
        for year, districts in ages_by_year.items()
        if len(districts) == DISTRICT_COUNT
        and all(len(ages) == YOUTH_MAX_AGE + 1 for ages in districts.values())
    }
    if not complete:
        raise RegistrationSourceError("no year has a complete snapshot for the selected month")
    return RegistrationHistory(
        month=month,
        snapshots=complete,
        totals={year: totals[year] for year in complete},
    )


def write_registration_extract(source: Path, destination: Path) -> Path:
    """Write the single-year-age rows of a registration CSV as compact Parquet.

    The extract keeps every column the reader uses, summed over gender, so
    :func:`load_registration_history` returns identical snapshots from it. It
    lets a deployment package the source at a fraction of the CSV's size.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_suffix(".parquet.tmp")
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"""
            COPY (
                SELECT "民國年"::SMALLINT AS "民國年",
                       "月"::TINYINT AS "月",
                       "區代碼"::SMALLINT AS "區代碼",
                       "年齡下限"::SMALLINT AS "年齡下限",
                       "年齡上限"::SMALLINT AS "年齡上限",
                       SUM("人數")::INTEGER AS "人數"
                FROM read_csv_auto(?)
                WHERE "年齡下限" = "年齡上限"
                GROUP BY ALL
                ORDER BY ALL
            ) TO '{_sql_path(staged)}' (FORMAT parquet, COMPRESSION zstd)
            """,
            [str(source)],
        )
    except duckdb.Error as exc:
        raise RegistrationSourceError(
            f"the registration extract could not be written: {str(exc)[:240]}"
        ) from exc
    finally:
        connection.close()
    staged.replace(destination)
    return destination


def _reader(source: Path) -> str:
    return "read_parquet(?)" if source.suffix == ".parquet" else "read_csv_auto(?)"


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")
