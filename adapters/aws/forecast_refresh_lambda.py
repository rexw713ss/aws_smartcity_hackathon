"""Workflow step: rebuild the youth population forecast after an upload publishes.

Feature: youth population forecast (docs/31), phase 2.

The published ``population`` dataset keeps only ages 18-35, but the cohort model
needs ages down to 18 minus the horizon, so this step reads the raw upload the
workflow just published rather than the curated table. Any upload that is not a
single-year-age registration file simply does not qualify and is skipped.

The step runs the same backtest and acceptance gate as ``make forecast``. It
publishes only a forecast that passes; a gate failure leaves the previous
forecast in place. It never fails the ingestion: every outcome is reported in
the payload and the state machine also catches errors around it.
"""

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from adapters.aws.s3_forecast_artifact import publish_forecast_to_s3
from youth_compass.forecasting.cohort import DEFAULT_WINDOW_YEARS
from youth_compass.forecasting.publication import (
    DEFAULT_HORIZON,
    PublicationError,
    build,
    validate_forecast_table,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Refresh the forecast from ``event['source_uri']`` when the upload published.

    Expects ``{"source_uri": "s3://bucket/key", "published": bool}``.
    """

    del context
    if event.get("published") is not True:
        return _outcome("skipped", "the upload was not published")
    source_uri = str(event.get("source_uri", ""))
    if not source_uri.startswith("s3://") or "/" not in source_uri[len("s3://") :]:
        return _outcome("skipped", "the upload has no s3:// source")
    bucket_name = os.environ["YOUTH_COMPASS_FORECASTS_BUCKET"]
    prefix = os.environ.get("YOUTH_COMPASS_FORECAST_PREFIX", "population/")
    region = os.environ.get("YOUTH_COMPASS_REGION", "us-east-1")

    source_bucket, _, key = source_uri[len("s3://") :].partition("/")
    work = Path(tempfile.mkdtemp(prefix="forecast-", dir="/tmp"))
    source = work / "source.csv"
    s3 = boto3.client("s3", region_name=region)
    s3.download_file(source_bucket, key, str(source))
    try:
        table, card = build(
            source,
            horizon_years=DEFAULT_HORIZON,
            window_years=DEFAULT_WINDOW_YEARS,
            generated_at=datetime.now(UTC).replace(microsecond=0),
        )
        validate_forecast_table(table, DEFAULT_HORIZON)
    except PublicationError as exc:
        # Not a registration file, too short, or no model beat the baseline.
        logger.info("forecast refresh skipped for %s: %s", source_uri, exc)
        return _outcome("skipped", str(exc)[:500])

    artifact = work / "current.parquet"
    card_path = work / "model-card.json"
    pq.write_table(table, artifact, compression="zstd")
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    card_uri, artifact_uri = publish_forecast_to_s3(
        artifact, card_path, bucket=bucket_name, prefix=prefix, client=s3
    )
    evaluation = card["evaluation"]
    assert isinstance(evaluation, dict)
    logger.info(
        "forecast refreshed from %s: model=%s base=%s coverage=%s",
        source_uri,
        evaluation["selected_model"],
        evaluation["base_period"],
        evaluation["rolling_coverage"],
    )
    return {
        "status": "published",
        "model_version": evaluation["selected_model"],
        "base_period": evaluation["base_period"],
        "rolling_coverage": evaluation["rolling_coverage"],
        "artifact_uri": artifact_uri,
        "model_card_uri": card_uri,
    }


def _outcome(status: str, reason: str) -> dict[str, Any]:
    return {"status": status, "reason": reason}
