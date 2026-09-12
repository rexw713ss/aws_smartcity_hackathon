"""S3 presigned-upload signer tests under moto, plus the upload endpoint.

Feature: upload-endpoint.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
import requests
from fastapi.testclient import TestClient
from moto import mock_aws

from adapters.aws.s3_uploads import S3UploadSigner, UploadNotPermittedError

REGION = "us-east-1"
BUCKET = "test-incoming-bucket"


def _create_state_machine() -> str:
    iam = boto3.client("iam", region_name=REGION)
    role = iam.create_role(
        RoleName="upload-workflow-role",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "states.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )
    response = boto3.client("stepfunctions", region_name=REGION).create_state_machine(
        name="upload-ingestion-workflow",
        definition=json.dumps(
            {"StartAt": "WaitForReview", "States": {"WaitForReview": {"Type": "Pass", "End": True}}}
        ),
        roleArn=role["Role"]["Arn"],
    )
    return response["stateMachineArn"]


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
        assert f"incoming/{result.job_id}/" in result.object_key
        assert result.object_key.endswith(".csv")
        assert "Content-Type" in result.fields
        assert result.fields["x-amz-meta-submitted-by"] == "steward"
        assert result.fields["x-amz-meta-job-id"] == result.job_id

    def test_presign_pdf_is_allowed(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        result = signer.presign_upload(content_type="application/pdf", submitted_by="steward")
        assert result.object_key.endswith(".pdf")

    def test_expiry_reflects_configured_lifetime(self, _bucket: None) -> None:
        before = datetime.now(UTC)
        signer = S3UploadSigner(bucket=BUCKET, region=REGION, expiry_seconds=60)
        result = signer.presign_upload(content_type="text/csv", submitted_by="steward")
        after = datetime.now(UTC)

        assert before + timedelta(seconds=60) <= result.expires_at
        assert result.expires_at <= after + timedelta(seconds=60)

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

    def test_returned_form_uploads_file_to_s3(self, _bucket: None) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        result = signer.presign_upload(
            content_type="text/csv",
            submitted_by="steward",
            original_filename="data.csv",
        )

        response = requests.post(
            result.url,
            data=result.fields,
            files={"file": ("data.csv", b"district,value\nBanqiao,42\n", "text/csv")},
            timeout=5,
        )

        assert response.status_code == 204
        stored = boto3.client("s3", region_name=REGION).get_object(
            Bucket=BUCKET,
            Key=result.object_key,
        )
        assert stored["Body"].read() == b"district,value\nBanqiao,42\n"

    @pytest.mark.parametrize("submitted_by", ["", "   ", "line\nbreak", "x" * 257])
    def test_invalid_submitter_is_rejected(
        self, _bucket: None, submitted_by: str
    ) -> None:
        signer = S3UploadSigner(bucket=BUCKET, region=REGION)
        with pytest.raises(UploadNotPermittedError, match="submitted_by"):
            signer.presign_upload(content_type="text/csv", submitted_by=submitted_by)


class TestUploadEndpoint:
    def test_upload_endpoint_returns_presigned_post(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            from apps.api.main import app

            client = TestClient(app)
            response = client.post(
                "/api/v1/uploads",
                json={"content_type": "text/csv", "submitted_by": "steward"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["objectKey"].startswith(f'incoming/{body["jobId"]}/')
        assert body["status"] == "pending"
        assert body["links"]["complete"].endswith(f'/{body["jobId"]}/complete')
        assert "url" in body and "fields" in body

    def test_disallowed_type_returns_415(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            from apps.api.main import app

            client = TestClient(app)
            response = client.post(
                "/api/v1/uploads",
                json={"content_type": "application/x-sh", "submitted_by": "steward"},
            )
        assert response.status_code == 415

    def test_unconfigured_bucket_returns_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTH_COMPASS_INCOMING_BUCKET", raising=False)
        from apps.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/uploads",
            json={"content_type": "text/csv", "submitted_by": "steward"},
        )
        assert response.status_code == 503

    def test_submitter_over_limit_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        from apps.api.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/uploads",
            json={"content_type": "text/csv", "submitted_by": "x" * 257},
        )
        assert response.status_code == 422

    def test_uploaded_object_starts_trackable_workflow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            monkeypatch.setenv("YOUTH_COMPASS_STATE_MACHINE_ARN", _create_state_machine())
            from apps.api.main import create_app

            client = TestClient(create_app(tmp_path))
            issued = client.post(
                "/api/v1/uploads",
                json={
                    "contentType": "text/csv",
                    "submittedBy": "steward",
                    "originalFilename": "population.csv",
                },
            ).json()
            upload = requests.post(
                issued["url"],
                data=issued["fields"],
                files={"file": ("population.csv", b"district,value\nBanqiao,42\n")},
                timeout=5,
            )
            assert upload.status_code == 204

            completed = client.post(
                issued["links"]["complete"],
                json={"objectKey": issued["objectKey"], "topicHint": "population"},
            )
            assert completed.status_code == 202
            assert completed.json()["jobId"] == issued["jobId"]
            assert completed.json()["status"] == "awaiting_approval"

            tracked = client.get(issued["links"]["job"])
            assert tracked.status_code == 200
            assert tracked.json()["jobId"] == issued["jobId"]
            assert tracked.json()["status"] == "awaiting_approval"

            repeated = client.post(
                issued["links"]["complete"],
                json={"objectKey": issued["objectKey"], "topicHint": "population"},
            )
            assert repeated.status_code == 202
            assert repeated.json()["jobId"] == issued["jobId"]

    def test_complete_before_s3_upload_returns_conflict(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        with mock_aws():
            boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
            monkeypatch.setenv("YOUTH_COMPASS_STATE_MACHINE_ARN", _create_state_machine())
            from apps.api.main import create_app

            client = TestClient(create_app(tmp_path))
            issued = client.post(
                "/api/v1/uploads",
                json={"contentType": "text/csv", "submittedBy": "steward"},
            ).json()
            response = client.post(
                issued["links"]["complete"],
                json={"objectKey": issued["objectKey"]},
            )
            assert response.status_code == 409
