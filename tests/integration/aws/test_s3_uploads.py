"""S3 presigned-upload signer tests under moto, plus the upload endpoint.

Feature: upload-endpoint.
"""

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from adapters.aws.s3_uploads import S3UploadSigner, UploadNotPermittedError

REGION = "us-east-1"
BUCKET = "test-incoming-bucket"


@pytest.fixture
def _bucket() -> None:
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        yield


class TestUploadSigner:
    def test_presign_csv_returns_url_and_generated_key(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        result = signer.presign_upload(content_type="text/csv", submitted_by="steward")
        assert result.url
        assert result.object_key.startswith("incoming/")
        assert result.object_key.endswith(".csv")
        assert "Content-Type" in result.fields
        assert result.fields["x-amz-meta-submitted-by"] == "steward"

    def test_presign_pdf_is_allowed(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        result = signer.presign_upload(content_type="application/pdf", submitted_by="steward")
        assert result.object_key.endswith(".pdf")

    def test_disallowed_content_type_rejected(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        with pytest.raises(UploadNotPermittedError):
            signer.presign_upload(content_type="application/x-sh", submitted_by="steward")

    def test_client_cannot_choose_the_key(self, _bucket: None) -> None:
        # Two uploads of the same filename get distinct generated keys.
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        a = signer.presign_upload(
            content_type="text/csv", submitted_by="s", original_filename="data.csv"
        )
        b = signer.presign_upload(
            content_type="text/csv", submitted_by="s", original_filename="data.csv"
        )
        assert a.object_key != b.object_key

    def test_original_filename_is_sanitized(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        result = signer.presign_upload(
            content_type="text/csv",
            submitted_by="s",
            original_filename="../../etc/passwd",
        )
        assert "/" not in result.fields["x-amz-meta-original-filename"]


class TestUploadEndpoint:
    def test_upload_endpoint_returns_presigned_post(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            from apps.api.main import app

            client = TestClient(app)
            response = client.post(
                "/uploads",
                json={"content_type": "text/csv", "submitted_by": "steward"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["object_key"].startswith("incoming/")
        assert "url" in body and "fields" in body

    def test_disallowed_type_returns_415(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            from apps.api.main import app

            client = TestClient(app)
            response = client.post(
                "/uploads",
                json={"content_type": "application/x-sh", "submitted_by": "steward"},
            )
        assert response.status_code == 415

    def test_unconfigured_bucket_returns_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTH_COMPASS_INCOMING_BUCKET", raising=False)
        from apps.api.main import app

        client = TestClient(app)
        response = client.post(
            "/uploads",
            json={"content_type": "text/csv", "submitted_by": "steward"},
        )
        assert response.status_code == 503
