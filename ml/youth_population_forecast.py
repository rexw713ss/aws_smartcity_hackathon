"""Backtest, select, and publish the district youth (18-35) population forecast.

Reads New Taipei single-year-age household registration, re-runs every candidate
from past origins, publishes only a model that beats the naive baseline at every
horizon, and writes two artifacts the API reads:

    data/forecasts/current.parquet    forecast points, intervals, and drivers
    data/forecasts/model-card.json    method, backtest, gate, and interval evidence

    uv run python -m ml.youth_population_forecast \
        --source "data/source/01_人口/_全部年度_全區.csv"

The published population dataset keeps only ages 18-35, while the cohort method
needs ages down to 18 minus the horizon, so the source file is read directly and
its SHA-256 is recorded for lineage. See docs/31-youth-population-forecast.md.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from youth_compass.forecasting.cohort import DEFAULT_WINDOW_YEARS, CohortInputError
from youth_compass.forecasting.publication import (
    DEFAULT_HORIZON,
    METRIC_CODE,
    PublicationError,
    build,
    validate_forecast_table,
)
from youth_compass.forecasting.registration import DISTRICT_COUNT

DEFAULT_SOURCE = Path("data/source/01_人口/_全部年度_全區.csv")
DEFAULT_OUTPUT_DIR = Path("data/forecasts")


def publish(table: pa.Table, card: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    """Validate staged artifacts, then promote the card and the forecast atomically."""

    from adapters.local import PrecomputedParquetForecastService
    from youth_compass.ports import ForecastRequest

    horizon = int(card["parameters"]["horizon_years"])  # type: ignore[index]
    validate_forecast_table(table, horizon)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / "current.parquet"
    card_path = output_dir / "model-card.json"
    staged_artifact = output_dir / "current.parquet.tmp"
    staged_card = output_dir / "model-card.json.tmp"
    pq.write_table(table, staged_artifact, compression="zstd")
    staged_card.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        result = PrecomputedParquetForecastService(
            staged_artifact, model_card=staged_card
        ).get_forecast(ForecastRequest(metric_code=METRIC_CODE, horizon_years=horizon))
        districts = {point.district_code for point in result.points}
        if len(districts) != DISTRICT_COUNT or len(result.points) != DISTRICT_COUNT * horizon:
            raise PublicationError("staged forecast does not cover every district and horizon")
        if result.evaluation is None:
            raise PublicationError("staged model card does not match the staged forecast")
    except Exception:
        staged_artifact.unlink(missing_ok=True)
        staged_card.unlink(missing_ok=True)
        raise
    # The card is promoted first: a reader that sees the new card with the old
    # forecast finds mismatched versions and omits the evaluation, never pairs
    # old numbers with new evidence.
    os.replace(staged_card, card_path)
    os.replace(staged_artifact, artifact)
    return artifact, card_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--horizon-years", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--window-years", type=int, default=DEFAULT_WINDOW_YEARS)
    parser.add_argument(
        "--s3-bucket",
        help="also upload the validated card and artifact to this forecasts bucket",
    )
    parser.add_argument("--s3-prefix", default="population/")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)
    try:
        table, card = build(
            args.source,
            horizon_years=args.horizon_years,
            window_years=args.window_years,
            generated_at=datetime.now(UTC).replace(microsecond=0),
        )
        artifact, card_path = publish(table, card, args.output_dir)
    except (PublicationError, CohortInputError) as exc:
        print(f"forecast not published: {exc}", file=sys.stderr)
        return 1
    evaluation = card["evaluation"]
    print(
        f"published {table.num_rows} points from {evaluation['selected_model']} "  # type: ignore[index]
        f"(base {evaluation['base_period']}) to {artifact} and {card_path}"  # type: ignore[index]
    )
    if args.s3_bucket:
        from adapters.aws.s3_forecast_artifact import publish_forecast_to_s3

        # Only the locally validated and promoted files are uploaded.
        uploaded = publish_forecast_to_s3(
            artifact,
            card_path,
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            region=args.region,
        )
        print("uploaded " + " and ".join(uploaded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
