"""Benchmark CSV ingestion sizes and the offline forecast build/read path."""

import argparse
import json
import resource
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from adapters.local.precomputed_forecast import PrecomputedParquetForecastService
from youth_compass.forecasting.cohort import DEFAULT_WINDOW_YEARS
from youth_compass.forecasting.publication import DEFAULT_HORIZON, METRIC_CODE, build
from youth_compass.ingestion import profile_csv
from youth_compass.mapping.geography import DISTRICTS
from youth_compass.ports import ForecastRequest
from youth_compass.transformation import TransformOptions, run_csv_transformation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes-mb", default="1,10,25")
    parser.add_argument(
        "--forecast-source",
        type=Path,
        default=Path("data/source/01_人口/_全部年度_全區.csv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/reports/data-pipeline-benchmark.json")
    )
    args = parser.parse_args()
    sizes = tuple(int(value) for value in args.sizes_mb.split(",") if value.strip())
    ingestion_results: list[dict[str, object]] = []
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "ingestion": ingestion_results,
    }
    with tempfile.TemporaryDirectory(prefix="youth-compass-benchmark-") as directory:
        root = Path(directory)
        for size_mb in sizes:
            source = root / f"population-{size_mb}mb.csv"
            rows = _write_csv(source, size_mb * 1_000_000)
            profile_started = time.perf_counter()
            profile = profile_csv(source)
            profile_seconds = time.perf_counter() - profile_started
            transform_started = time.perf_counter()
            manifest = run_csv_transformation(
                source,
                TransformOptions(
                    approved_by="benchmark",
                    dataset_id=f"benchmark_population_{size_mb}mb",
                    topic_hint="population",
                    curated_root=root / "curated",
                    quarantine_root=root / "quarantined",
                ),
            )
            transform_seconds = time.perf_counter() - transform_started
            ingestion_results.append(
                {
                    "target_mb": size_mb,
                    "bytes": source.stat().st_size,
                    "rows": rows,
                    "profile_rows": profile.row_count,
                    "profile_seconds": profile_seconds,
                    "profile_rows_per_second": rows / profile_seconds,
                    "transform_seconds": transform_seconds,
                    "transform_rows_per_second": rows / transform_seconds,
                    "status": manifest.status.value,
                    "observations": manifest.observation_count,
                }
            )

        forecast_started = time.perf_counter()
        table, card = build(
            args.forecast_source,
            horizon_years=DEFAULT_HORIZON,
            window_years=DEFAULT_WINDOW_YEARS,
            generated_at=datetime.now(UTC).replace(microsecond=0),
        )
        forecast_seconds = time.perf_counter() - forecast_started
        forecast_path = Path("data/forecasts/current.parquet")
        service = PrecomputedParquetForecastService(forecast_path)
        read_latencies: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            result = service.get_forecast(
                ForecastRequest(metric_code=METRIC_CODE, horizon_years=DEFAULT_HORIZON)
            )
            read_latencies.append((time.perf_counter() - started) * 1000)
        report["forecast"] = {
            "source_bytes": args.forecast_source.stat().st_size,
            "build_seconds": forecast_seconds,
            "points": table.num_rows,
            "selected_model": card["evaluation"]["selected_model"],  # type: ignore[index]
            "rolling_coverage": card["evaluation"]["rolling_coverage"],  # type: ignore[index]
            "read_requests": len(read_latencies),
            "read_mean_ms": sum(read_latencies) / len(read_latencies),
            "read_max_ms": max(read_latencies),
            "returned_points": len(result.points),
        }
        report["peak_rss_mb"] = _peak_rss_mb()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _write_csv(path: Path, target_bytes: int) -> int:
    header = "year,month,district,age,gender,population\n"
    rows = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        while handle.tell() < target_bytes:
            district = DISTRICTS[rows % len(DISTRICTS)]
            month = rows // len(DISTRICTS) % 12 + 1
            age = rows // (len(DISTRICTS) * 12) % 18 + 18
            gender = "M" if rows // (len(DISTRICTS) * 12 * 18) % 2 == 0 else "F"
            year = 2000 + rows // (len(DISTRICTS) * 12 * 18 * 2)
            handle.write(f"{year},{month},{district.name},{age},{gender},{100 + rows % 900}\n")
            rows += 1
    return rows


def _peak_rss_mb() -> float:
    # macOS reports bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / 1_000_000 if value > 10_000_000 else value / 1024


if __name__ == "__main__":
    main()
