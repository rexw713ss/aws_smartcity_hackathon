"""S3/EventBridge upload event starts the correlated workflow."""

import boto3
import requests
from moto import mock_aws

from adapters.aws.s3_uploads import S3UploadSigner
from adapters.aws.upload_event_handler import handler
from tests.integration.aws.test_s3_uploads import BUCKET, REGION, _create_state_machine


def test_eventbridge_s3_event_starts_correlated_job(monkeypatch) -> None:
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        state_machine_arn = _create_state_machine()
        monkeypatch.setenv("YOUTH_COMPASS_INCOMING_BUCKET", BUCKET)
        monkeypatch.setenv("YOUTH_COMPASS_STATE_MACHINE_ARN", state_machine_arn)
        monkeypatch.setenv("YOUTH_COMPASS_REGION", REGION)
        presigned = S3UploadSigner(bucket=BUCKET, region=REGION).presign_upload(
            content_type="text/csv",
            submitted_by="steward",
            original_filename="population.csv",
        )
        uploaded = requests.post(
            presigned.url,
            data=presigned.fields,
            files={"file": ("population.csv", b"district,value\nBanqiao,42\n")},
            timeout=5,
        )
        assert uploaded.status_code == 204

        result = handler(
            {
                "detail": {
                    "bucket": {"name": BUCKET},
                    "object": {"key": presigned.object_key},
                }
            },
            None,
        )

        assert result["job_id"] == presigned.job_id
        assert result["status"] == "awaiting_approval"
