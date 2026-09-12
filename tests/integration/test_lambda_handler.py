"""The Lambda entrypoint must survive a read-only deployment package.

Regression coverage: the first deployment returned 500 on every route because
apps.api.main builds an application at import time using the default data root,
and Lambda unpacks the package read-only at /var/task. Nothing in the offline
suite exercised that, because locally the data root is always writable.
"""

import importlib
import json
from pathlib import Path

import pytest


def _event(method: str, path: str) -> dict[str, object]:
    """A minimal API Gateway HTTP API (payload format 2.0) event."""
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "test.execute-api.us-east-1.amazonaws.com"},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "203.0.113.1"},
            "stage": "$default",
            "requestId": "request-1",
            "apiId": "api-1",
        },
        "isBase64Encoded": False,
    }


@pytest.fixture
def handler_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> object:
    """Import the handler with a read-only baked root, as Lambda would."""
    baked = tmp_path / "baked"
    (baked / "metadata").mkdir(parents=True)
    (baked / "curated").mkdir()
    # Read-only, exactly like the unpacked deployment package.
    baked.chmod(0o500)
    monkeypatch.setenv("YOUTH_COMPASS_BAKED_DATA_ROOT", str(baked))
    monkeypatch.setenv("YOUTH_COMPASS_DATA_ROOT", str(tmp_path / "writable"))

    import apps.api.lambda_handler as module

    reloaded = importlib.reload(module)
    yield reloaded
    baked.chmod(0o700)


class TestLambdaHandler:
    def test_health_succeeds_with_a_read_only_package(self, handler_module: object) -> None:
        response = handler_module.handler(_event("GET", "/health"), None)  # type: ignore[attr-defined]

        assert response["statusCode"] == 200
        assert json.loads(response["body"])["status"] == "ok"

    def test_catalog_read_succeeds(self, handler_module: object) -> None:
        response = handler_module.handler(_event("GET", "/api/v1/datasets"), None)  # type: ignore[attr-defined]

        assert response["statusCode"] == 200

    def test_writable_root_is_seeded_with_the_required_directories(
        self, handler_module: object, tmp_path: Path
    ) -> None:
        writable = tmp_path / "writable"

        # The offline runtime opens a SQLite index and object store under these.
        for name in ("incoming", "curated", "quarantined", "metadata", "features"):
            assert (writable / name).is_dir(), f"{name} was not created"

    def test_preparation_is_idempotent_for_a_warm_container(self, handler_module: object) -> None:
        # A warm invocation re-runs nothing, but calling again must not raise.
        first = handler_module._prepare_writable_data_root()  # type: ignore[attr-defined]
        second = handler_module._prepare_writable_data_root()  # type: ignore[attr-defined]

        assert first == second
