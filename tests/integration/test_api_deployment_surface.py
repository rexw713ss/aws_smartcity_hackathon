"""CORS and write-token behaviour for the publicly deployed API.

Reads stay public so a demo audience can browse without credentials; the
mutating endpoints require a shared secret, because approving an ingestion job
publishes data to the curated zone and the Glue catalog.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.security import WRITE_TOKEN_HEADER
from youth_compass.config import ApiSettings, AppSettings

ORIGIN = "https://dashboard.example.org"
SECRET = "test-write-secret"


def _client(tmp_path: Path, **api_overrides: object) -> TestClient:
    """Build an app whose settings carry the supplied API overrides."""
    settings = AppSettings(api=ApiSettings(**api_overrides))  # type: ignore[arg-type]
    app = create_app(tmp_path / "data")
    app.state.settings = settings
    return TestClient(app)


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
