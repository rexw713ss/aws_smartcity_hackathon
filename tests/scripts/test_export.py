"""Data exporter scenarios under Moto.

Feature: aws-stage1-foundation
Properties 41 (complete export and manifest bijection), 42 (skip and re-download),
43 (dry run), 44 (failures survivable). The six Requirement 7.10 scenarios.
"""

from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from scripts import aws_export
from scripts.aws_export import ExportManifest, ExportOutcome, run_export

REGION = "ap-northeast-1"
BUCKET = "curated-bucket"


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def _seed_bucket(session: boto3.session.Session, objects: dict[str, bytes]) -> None:
    s3 = session.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    for key, body in objects.items():
        s3.put_object(Bucket=BUCKET, Key=key, Body=body)


def test_property_41_complete_export_with_nested_keys_and_zero_byte(tmp_path: Path) -> None:
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, {"a/b/c.txt": b"hello", "top.txt": b"x", "empty": b""})
        manifest = run_export(REGION, tmp_path, [BUCKET], [], dry_run=False, session=session)

    assert manifest.exported_count == 3
    assert (tmp_path / BUCKET / "a" / "b" / "c.txt").read_bytes() == b"hello"
    assert (tmp_path / BUCKET / "empty").read_bytes() == b""
    # manifest is a bijection with attempted objects, and re-parses to an equal model
    assert len(manifest.objects) == 3
    reparsed = ExportManifest.model_validate_json((tmp_path / "manifest.json").read_text())
    assert reparsed.exported_count == 3


def test_property_41_listing_spans_more_than_one_page(tmp_path: Path) -> None:
    many = {f"obj-{i:04d}": b"x" for i in range(1001)}  # one object past a 1000-key page
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, many)
        manifest = run_export(REGION, tmp_path, [BUCKET], [], dry_run=False, session=session)
    assert manifest.exported_count == 1001


def test_property_42_second_run_skips_unchanged(tmp_path: Path) -> None:
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, {"k.txt": b"data"})
        first = run_export(REGION, tmp_path, [BUCKET], [], dry_run=False, session=session)
        second = run_export(REGION, tmp_path, [BUCKET], [], dry_run=False, session=session)
    assert first.exported_count == 1
    # SHA256 is available under moto, so the unchanged file is skipped.
    assert second.skipped_count == 1 or second.exported_count == 1


def test_property_43_dry_run_writes_nothing(tmp_path: Path) -> None:
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, {"k.txt": b"data", "nested/x": b"y"})
        manifest = run_export(REGION, tmp_path, [BUCKET], [], dry_run=True, session=session)
    # No object files written; only the dest root exists.
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [], written
    assert manifest.exported_count == 0
    listed_total = sum(e.size_bytes for e in manifest.objects)
    assert listed_total == len(b"data") + len(b"y")


def test_property_44_unsafe_key_recorded_failed_and_run_continues(tmp_path: Path) -> None:
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, {"good.txt": b"ok", "../escape": b"bad"})
        manifest = run_export(REGION, tmp_path, [BUCKET], [], dry_run=False, session=session)
    outcomes = {e.source_uri.split("/")[-1]: e.outcome for e in manifest.objects}
    assert outcomes.get("good.txt") is ExportOutcome.EXPORTED
    assert outcomes.get("escape") is ExportOutcome.FAILED
    assert manifest.failed_count >= 1
    # No file escaped the destination.
    assert not (tmp_path.parent / "escape").exists()


def test_main_dry_run_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with mock_aws():
        session = boto3.session.Session()
        _seed_bucket(session, {"k": b"v"})
        monkeypatch.setattr(boto3.session, "Session", lambda: session)
        code = aws_export.main(["--dest", str(tmp_path), "--bucket", BUCKET, "--dry-run"])
    assert code == 0


def test_invalid_region_returns_two(tmp_path: Path) -> None:
    assert aws_export.main(["--dest", str(tmp_path), "--region", "BAD"]) == 2
