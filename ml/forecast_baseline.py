"""Generate the precomputed forecast artifact the API's forecast service reads.

Reads a published population series, fits the deterministic baseline
(youth_compass.forecasting), and writes Parquet in exactly the schema
PrecomputedParquetForecastService expects:

    metric_code, district_code, year_gregorian, value, lower, upper,
    model_version, generated_at

Two sources:

    # from the published curated table in Athena (the deployed reality)
    uv run python -m ml.forecast_baseline --from-athena \
        --database youth_compass_hackathon --table population \
        --workgroup youthcompasshackathon-analytics \
        --results-bucket youthcompasshackathon-metadata-765996595659

    # from a local CSV (offline, and what the tests use)
    uv run python -m ml.forecast_baseline --from-csv data/samples/population_multi_year.csv

The output defaults to data/forecasts/current.parquet, the path the local
forecast service reads. This is a batch artifact generator — no endpoint, no
training job, no always-on cost. See docs/aws-workstream-status.md.
"""

import argparse
import csv
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from youth_compass.forecasting import MODEL_VERSION, ForecastInputError, forecast_series

_DEFAULT_OUTPUT = Path("data/forecasts/current.parquet")
_DEFAULT_METRIC = "population_count"
_DEFAULT_HORIZON = 5

# The artifact schema PrecomputedParquetForecastService reads.
_ARTIFACT_SCHEMA = pa.schema(
    [
        pa.field("metric_code", pa.string(), nullable=False),
        pa.field("district_code", pa.string(), nullable=False),
        pa.field("year_gregorian", pa.int32(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("lower", pa.float64(), nullable=False),
        pa.field("upper", pa.float64(), nullable=False),
        pa.field("model_version", pa.string(), nullable=False),
        pa.field("generated_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

# A series keyed by district code -> (year, value) points.
Series = dict[str, list[tuple[int, float]]]


def _series_from_csv(path: Path) -> Series:
    """Read district population history from a `year,district,...,population` CSV.

    District names are normalised to canonical codes so the artifact keys match
    the curated data and the copilot's district identity.
    """
    from youth_compass.mapping.geography import normalize_district

    series: Series = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            district = normalize_district(row.get("district"))
            if district is None:
                continue
            try:
                year = int(str(row["year"]).strip())
                value = float(str(row["population"]).strip())
            except (KeyError, ValueError):
                continue
            series[district.code].append((year, value))
    return series


def _series_from_athena(
    *, database: str, table: str, workgroup: str, results_bucket: str, region: str, metric: str
) -> Series:
    """Read the district-year population series from the published Glue table."""
    from adapters.aws.athena_query import AthenaQueryEngine
    from youth_compass.ports.query_engine import QuerySpec

    engine = AthenaQueryEngine(
        database=database,
        workgroup=workgroup,
        output_bucket=results_bucket,
        region=region,
        allowed_tables={table},
        allowed_metrics={"metric_value"},
        allowed_dimensions={"district_code", "year_gregorian", "metric_code"},
    )
    result = engine.execute(
        QuerySpec(
            table=table,
            dimensions=["district_code", "year_gregorian"],
            metrics=["metric_value"],
            filters={"metric_code": metric},
            group_by_dimensions=True,
            max_rows=100_000,
        )
    )
    index = {name: position for position, name in enumerate(result.columns)}
    series: Series = defaultdict(list)
    for row in result.rows:
        code = row[index["district_code"]]
        year = row[index["year_gregorian"]]
        value = row[index["metric_value"]]
        if code is None or year is None or value is None:
            continue
        series[str(code)].append((int(year), float(value)))  # type: ignore[arg-type]
    return series


def _write_artifact(
    points: Sequence[object],
    *,
    metric_code: str,
    generated_at: datetime,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    columns: Mapping[str, list[object]] = {
        "metric_code": [metric_code] * len(points),
        "district_code": [p.district_code for p in points],  # type: ignore[attr-defined]
        "year_gregorian": [p.year_gregorian for p in points],  # type: ignore[attr-defined]
        "value": [p.value for p in points],  # type: ignore[attr-defined]
        "lower": [p.lower for p in points],  # type: ignore[attr-defined]
        "upper": [p.upper for p in points],  # type: ignore[attr-defined]
        "model_version": [MODEL_VERSION] * len(points),
        "generated_at": [generated_at] * len(points),
    }
    # Atomic replace so a reader never sees a half-written artifact.
    staging = output.with_suffix(".parquet.tmp")
    pq.write_table(pa.table(columns, schema=_ARTIFACT_SCHEMA), staging, compression="zstd")
    staging.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-csv", type=Path, help="local CSV history")
    source.add_argument("--from-athena", action="store_true", help="published Glue table")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--metric-code", default=_DEFAULT_METRIC)
    parser.add_argument("--horizon-years", type=int, default=_DEFAULT_HORIZON)
    # Athena source options.
    parser.add_argument("--database")
    parser.add_argument("--table", default="population")
    parser.add_argument("--workgroup")
    parser.add_argument("--results-bucket")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    if args.from_athena:
        missing = [
            name for name in ("database", "workgroup", "results_bucket") if not getattr(args, name)
        ]
        if missing:
            parser.error("--from-athena requires: " + ", ".join(f"--{m}" for m in missing))
        series = _series_from_athena(
            database=args.database,
            table=args.table,
            workgroup=args.workgroup,
            results_bucket=args.results_bucket,
            region=args.region,
            metric=args.metric_code,
        )
    else:
        series = _series_from_csv(args.from_csv)

    try:
        points = forecast_series(series, horizon_years=args.horizon_years)
    except ForecastInputError as exc:
        print(f"cannot build a forecast: {exc}", file=sys.stderr)
        return 1

    _write_artifact(
        points,
        metric_code=args.metric_code,
        generated_at=datetime.now(UTC),
        output=args.output,
    )
    districts = sorted({p.district_code for p in points})
    print(
        f"wrote {len(points)} forecast points for {len(districts)} district(s) "
        f"to {args.output} (model {MODEL_VERSION})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
