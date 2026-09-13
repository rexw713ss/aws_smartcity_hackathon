"""The workflow's forecast refresh step: publish on a qualifying upload, skip otherwise."""

from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from adapters.aws import forecast_refresh_lambda
from adapters.aws.s3_forecast_artifact import S3ForecastArtifactService
from tests.support.registration_source import write_registration_source
from youth_compass.ports import ForecastRequest

_INCOMING = "incoming-bucket"
_FORECASTS = "forecasts-bucket"


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("YOUTH_COMPASS_FORECASTS_BUCKET", _FORECASTS)
    monkeypatch.setenv("YOUTH_COMPASS_REGION", "us-east-1")
    real_mkdtemp = forecast_refresh_lambda.tempfile.mkdtemp
    monkeypatch.setattr(
        forecast_refresh_lambda.tempfile,
        "mkdtemp",
        lambda prefix, dir: real_mkdtemp(prefix=prefix, dir=str(tmp_path)),
    )
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_INCOMING)
        client.create_bucket(Bucket=_FORECASTS)
        yield client


def _upload(s3, tmp_path: Path, *, shrinking: bool) -> str:  # type: ignore[no-untyped-def]
    source = tmp_path / "registration.csv"
    write_registration_source(source, shrinking=shrinking)
    s3.upload_file(str(source), _INCOMING, "incoming/job-1/registration.csv")
    return f"s3://{_INCOMING}/incoming/job-1/registration.csv"


def test_a_published_registration_upload_refreshes_the_forecast(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    uri = _upload(s3, tmp_path, shrinking=True)

    outcome = forecast_refresh_lambda.handler({"source_uri": uri, "published": True}, None)

    assert outcome["status"] == "published"
    assert outcome["base_period"] == "2023-07"
    result = S3ForecastArtifactService(
        _FORECASTS, "population/", tmp_path / "cache", client=s3
    ).get_forecast(ForecastRequest(metric_code="population_count", horizon_years=5))
    assert len(result.points) == 29 * 5
    assert result.evaluation is not None


def test_an_unpublished_upload_is_skipped_without_reading_it(s3) -> None:  # type: ignore[no-untyped-def]
    outcome = forecast_refresh_lambda.handler(
        {"source_uri": f"s3://{_INCOMING}/incoming/missing.csv", "published": False}, None
    )

    assert outcome == {"status": "skipped", "reason": "the upload was not published"}


def test_an_upload_in_another_layout_is_skipped(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    other = tmp_path / "employment.csv"
    other.write_text("stat_year,area,job_seekers\n115,板橋,1250\n", encoding="utf-8")
    s3.upload_file(str(other), _INCOMING, "incoming/job-2/employment.csv")

    outcome = forecast_refresh_lambda.handler(
        {"source_uri": f"s3://{_INCOMING}/incoming/job-2/employment.csv", "published": True},
        None,
    )

    assert outcome["status"] == "skipped"
    assert s3.list_objects_v2(Bucket=_FORECASTS).get("KeyCount") == 0


def test_a_forecast_that_fails_the_gate_is_not_published(s3, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    uri = _upload(s3, tmp_path, shrinking=False)

    outcome = forecast_refresh_lambda.handler({"source_uri": uri, "published": True}, None)

    assert outcome["status"] == "skipped"
    assert "acceptance gate failed" in outcome["reason"]
    assert s3.list_objects_v2(Bucket=_FORECASTS).get("KeyCount") == 0
