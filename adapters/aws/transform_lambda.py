"""Lambda handler for the deterministic transforms.

Feature: aws-stage2-adapters, Requirement 6.

Calls the existing ``profile_csv`` and ``analyze_mapping`` functions — no
reimplementation. The handler code lives under ``adapters/aws/`` and is not
imported by any module under ``src/youth_compass/``.
"""

import json
from pathlib import Path
from typing import Any

from youth_compass.domain.errors import YouthCompassError
from youth_compass.ingestion.csv_profiler import profile_csv
from youth_compass.mapping.engine import MappingOptions, analyze_mapping


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Dispatches to ``profile`` or ``analyze`` actions.

    Event shape::

        {"action": "profile", "source_path": "/tmp/file.csv"}
        {"action": "analyze", "source_path": "/tmp/file.csv", "topic_hint": "..."}
    """
    action = event.get("action", "")
    source_path = event.get("source_path", "")

    if not source_path:
        return _error("source_path is required")

    try:
        if action == "profile":
            return _profile(Path(source_path))
        if action == "analyze":
            return _analyze(Path(source_path), topic_hint=event.get("topic_hint"))
        return _error(f"unknown action: {action!r}; expected 'profile' or 'analyze'")
    except YouthCompassError as exc:
        return _error(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _error(f"unexpected: {type(exc).__name__}: {exc}"[:500])


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
