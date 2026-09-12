"""Lambda handler for the deterministic transforms.

Feature: aws-stage2-adapters, Requirement 6.

Calls the existing ``profile_csv`` and ``analyze_mapping`` functions — no
reimplementation. The handler code lives under ``adapters/aws/`` and is not
imported by any module under ``src/youth_compass/``.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

from youth_compass.domain.errors import YouthCompassError
from youth_compass.ingestion.csv_profiler import profile_csv
from youth_compass.mapping.engine import MappingOptions, analyze_mapping


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Dispatches to ``profile`` or ``analyze`` actions.

    Two input modes:

    - Local path (used by tests and local invocation)::

        {"action": "profile", "source_path": "/tmp/file.csv"}
        {"action": "analyze", "source_path": "/tmp/file.csv", "topic_hint": "..."}

    - S3 object (used by the Step Functions workflow)::

        {"action": "analyze", "bucket": "...", "key": "incoming/x.csv"}
    """
    action = event.get("action", "")
    bucket = event.get("bucket")
    key = event.get("key")
    source_uri = event.get("source_uri", "")
    source_path = event.get("source_path", "")

    # Accept an s3:// URI (workflow input) and split it into bucket + key.
    if source_uri.startswith("s3://") and not (bucket and key):
        rest = source_uri[len("s3://") :]
        bucket, _, key = rest.partition("/")

    if not source_path and not (bucket and key):
        return _error("one of source_path, source_uri, or (bucket + key) is required")

    try:
        source = _download_from_s3(bucket, key) if bucket and key else Path(source_path)
        if action == "profile":
            return _profile(source)
        if action == "analyze":
            return _analyze(source, topic_hint=event.get("topic_hint"))
        return _error(f"unknown action: {action!r}; expected 'profile' or 'analyze'")
    except YouthCompassError as exc:
        return _error(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _error(f"unexpected: {type(exc).__name__}: {exc}"[:500])


def _download_from_s3(bucket: str, key: str) -> Path:
    """Download an S3 object to a temp file and return its path.

    boto3 is imported lazily so the local-path mode and its tests never require
    AWS libraries or credentials.
    """
    import boto3

    suffix = Path(key).suffix or ".csv"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    import os

    os.close(fd)
    boto3.client("s3").download_file(bucket, key, tmp)
    return Path(tmp)


def _profile(source: Path) -> dict[str, Any]:
    profile = profile_csv(source)
    return {"status": "ok", "action": "profile", "result": json.loads(profile.model_dump_json())}


def _analyze(source: Path, *, topic_hint: str | None = None) -> dict[str, Any]:
    profile = profile_csv(source)
    options = MappingOptions(topic_hint=topic_hint) if topic_hint else None
    analysis = analyze_mapping(profile, options)
    return {"status": "ok", "action": "analyze", "result": json.loads(analysis.model_dump_json())}


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}
