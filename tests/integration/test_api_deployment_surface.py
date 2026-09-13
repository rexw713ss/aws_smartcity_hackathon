"""CORS and write-token behaviour for the publicly deployed API.

Reads stay public so a demo audience can browse without credentials; the
mutating endpoints require a shared secret, because approving an ingestion job
publishes data to the curated zone and the Glue catalog.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.api import security
from apps.api.main import create_app
from apps.api.security import WRITE_TOKEN_HEADER
from youth_compass.config import ApiSettings, AppSettings

ORIGIN = "https://dashboard.example.org"
SECRET = "test-write-secret"
ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:write-AbCdEf"
ALLOWED_IP = "60.250.71.45"


def _client(tmp_path: Path, **api_overrides: object) -> TestClient:
    """Build an app whose settings carry the supplied API overrides."""
    settings = AppSettings(api=ApiSettings(**api_overrides))  # type: ignore[arg-type]
    app = create_app(tmp_path / "data")
    app.state.settings = settings
    return TestClient(app)


class TestSourceIpAllowlist:
    def test_unlisted_source_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_ALLOWED_SOURCE_IPS", ALLOWED_IP)
        client = TestClient(create_app(tmp_path / "data"), client=("203.0.113.10", 50000))

        response = client.get("/health")

        assert response.status_code == 403

    def test_listed_source_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_ALLOWED_SOURCE_IPS", ALLOWED_IP)
        client = TestClient(create_app(tmp_path / "data"), client=(ALLOWED_IP, 50000))

        response = client.get("/health")

        assert response.status_code == 200


class TestCors:
    def test_no_cors_headers_when_no_origin_is_configured(self, tmp_path: Path) -> None:
        # Default is closed: nothing is exposed cross-origin until configured.
        client = _client(tmp_path)

        response = client.get("/health", headers={"Origin": ORIGIN})

        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_configured_origin_is_echoed_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The middleware is installed while create_app runs, so the origin has
        # to be in the environment before the app is built.
        monkeypatch.setenv("YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS", ORIGIN)
        client = TestClient(create_app(tmp_path / "data"))

        response = client.get("/health", headers={"Origin": ORIGIN})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN

    def test_preflight_allows_the_write_token_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without this the browser would block every guarded write.
        monkeypatch.setenv("YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS", ORIGIN)
        client = TestClient(create_app(tmp_path / "data"))

        response = client.options(
            "/api/v1/uploads",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": WRITE_TOKEN_HEADER,
            },
        )

        assert response.status_code == 200
        allowed = response.headers["access-control-allow-headers"].lower()
        assert WRITE_TOKEN_HEADER.lower() in allowed

    def test_an_unlisted_origin_is_not_echoed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS", ORIGIN)
        client = TestClient(create_app(tmp_path / "data"))

        response = client.get("/health", headers={"Origin": "https://evil.example"})

        assert response.headers.get("access-control-allow-origin") != "https://evil.example"

    def test_origins_parse_from_a_comma_separated_string(self) -> None:
        # Lambda environment variables are strings, never lists.
        settings = ApiSettings(cors_allowed_origins="https://a.example, https://b.example")

        assert settings.allowed_origins == ("https://a.example", "https://b.example")

    def test_origins_also_accept_a_yaml_list(self) -> None:
        settings = ApiSettings(cors_allowed_origins=["https://a.example", "https://b.example"])  # type: ignore[arg-type]

        assert settings.allowed_origins == ("https://a.example", "https://b.example")

    def test_nested_env_var_populates_the_origins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regression: a sequence-typed field could not be populated this way,
        # because pydantic-settings JSON-decodes complex types from the env.
        monkeypatch.setenv("YOUTH_COMPASS_API__CORS_ALLOWED_ORIGINS", "https://a.example")

        assert AppSettings().api.allowed_origins == ("https://a.example",)


class TestWriteToken:
    def test_reads_stay_public_when_a_secret_is_configured(self, tmp_path: Path) -> None:
        client = _client(tmp_path, write_secret=SECRET)

        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/datasets").status_code == 200

    def test_decision_without_a_token_is_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path, write_secret=SECRET)

        response = client.post(
            "/api/v1/ingestion-jobs/job-1/decision",
            json={"decision": "approve", "decidedBy": "reviewer"},
        )

        assert response.status_code == 401
        assert WRITE_TOKEN_HEADER in response.json()["detail"]

    def test_decision_with_a_wrong_token_is_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path, write_secret=SECRET)

        response = client.post(
            "/api/v1/ingestion-jobs/job-1/decision",
            json={"decision": "approve", "decidedBy": "reviewer"},
            headers={WRITE_TOKEN_HEADER: "wrong"},
        )

        assert response.status_code == 401

    def test_upload_signing_without_a_token_is_rejected(self, tmp_path: Path) -> None:
        client = _client(tmp_path, write_secret=SECRET)

        response = client.post(
            "/api/v1/uploads",
            json={"contentType": "text/csv", "submittedBy": "steward"},
        )

        assert response.status_code == 401

    def test_a_correct_token_passes_the_guard(self, tmp_path: Path) -> None:
        client = _client(tmp_path, write_secret=SECRET)

        response = client.post(
            "/api/v1/ingestion-jobs/job-1/decision",
            json={"decision": "approve", "decidedBy": "reviewer"},
            headers={WRITE_TOKEN_HEADER: SECRET},
        )

        # Past the guard: the job genuinely does not exist, which is a 404, not
        # a 401. That distinction is the point of this assertion.
        assert response.status_code != 401

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/ingestion-jobs/job-1/decision", "/api/v1/uploads"],
    )
    def test_guard_is_inactive_when_no_secret_is_configured(
        self, tmp_path: Path, path: str
    ) -> None:
        # Local development and the offline suite must behave as before.
        client = _client(tmp_path)

        response = client.post(path, json={})

        assert response.status_code != 401

    def test_source_acquisition_without_a_token_is_rejected(self, tmp_path: Path) -> None:
        # Acquisition snapshots a source into the incoming zone and starts an
        # ingestion job, so it is a write and belongs behind the same guard.
        client = _client(tmp_path, write_secret=SECRET)

        response = client.post(
            "/api/v1/copilot/acquisitions",
            json={"candidateId": "moi-population", "submittedBy": "steward"},
        )

        assert response.status_code == 401


class TestWriteSecretFromSecretsManager:
    """A deployment stores the secret in Secrets Manager, not in an env var."""

    def test_the_guard_reads_the_expected_value_from_the_secret_store(self, tmp_path: Path) -> None:
        calls: list[str] = []

        def fake_fetch(arn: str) -> str:
            calls.append(arn)
            return SECRET

        security._secret_cache.clear()
        client = _client(tmp_path, write_secret_arn=ARN)
        with patch.object(security, "_fetch_secret", fake_fetch):
            rejected = client.post("/api/v1/uploads", json={})
            accepted = client.post(
                "/api/v1/uploads",
                json={"contentType": "text/csv", "submittedBy": "steward"},
                headers={WRITE_TOKEN_HEADER: SECRET},
            )

        assert rejected.status_code == 401
        assert accepted.status_code != 401
        assert calls == [ARN, ARN]  # once per guarded request; the stub bypasses the cache

    def test_a_literal_secret_still_wins(self, tmp_path: Path) -> None:
        # Local development and the offline suite configure one directly, and
        # must never reach the network for it.
        client = _client(tmp_path, write_secret=SECRET, write_secret_arn=ARN)

        def explode(arn: str) -> str:
            raise AssertionError("the secret store must not be consulted")

        with patch.object(security, "_fetch_secret", explode):
            response = client.post(
                "/api/v1/uploads",
                json={"contentType": "text/csv", "submittedBy": "steward"},
                headers={WRITE_TOKEN_HEADER: SECRET},
            )

        assert response.status_code != 401

    def test_an_unreachable_secret_store_fails_closed(self, tmp_path: Path) -> None:
        # A write must be refused, never allowed through, when the expected
        # value cannot be read.
        security._secret_cache.clear()
        client = _client(tmp_path, write_secret_arn=ARN)

        def explode(arn: str) -> str:
            raise RuntimeError("secretsmanager is unreachable")

        with patch.object(security, "_fetch_secret", explode):
            response = client.post(
                "/api/v1/uploads",
                json={"contentType": "text/csv", "submittedBy": "steward"},
                headers={WRITE_TOKEN_HEADER: SECRET},
            )

        assert response.status_code == 503

    def test_the_cache_is_reused_within_its_ttl(self, tmp_path: Path) -> None:
        calls: list[str] = []

        class FakeClient:
            def get_secret_value(self, SecretId: str) -> dict[str, str]:
                calls.append(SecretId)
                return {"SecretString": SECRET}

        security._secret_cache.clear()
        with patch("boto3.client", lambda name: FakeClient()):
            assert security._fetch_secret(ARN) == SECRET
            assert security._fetch_secret(ARN) == SECRET
        security._secret_cache.clear()

        assert calls == [ARN]


class TestErrorMessages:
    """Domain failures must not hand the caller internal server topology."""

    def test_a_server_side_failure_returns_a_generic_message(self, tmp_path: Path) -> None:
        from youth_compass.domain import YouthCompassError

        client = _client(tmp_path)
        app = client.app

        @app.get("/test/boom")  # type: ignore[union-attr]
        def boom() -> None:
            raise YouthCompassError("/srv/secret/path failed on arn:aws:iam::1234:role/admin")

        response = client.get("/test/boom")

        assert response.status_code == 500
        assert response.json()["error"]["message"] == "the request could not be completed"

    def test_a_client_error_keeps_its_reason_but_redacts_paths_and_arns(
        self, tmp_path: Path
    ) -> None:
        from youth_compass.domain import QueryExecutionError

        client = _client(tmp_path)
        app = client.app

        @app.get("/test/query-boom")  # type: ignore[union-attr]
        def query_boom() -> None:
            raise QueryExecutionError(
                "feature materialization is unavailable: /var/task/data/features.parquet"
            )

        response = client.get("/test/query-boom")

        assert response.status_code == 422
        message = response.json()["error"]["message"]
        assert "feature materialization is unavailable" in message
        assert "/var/task" not in message
