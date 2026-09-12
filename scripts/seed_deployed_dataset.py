"""Push one source file through the deployed ingestion API.

The deployed environment starts empty: curated data lives in S3 and DynamoDB,
not in the repository, so a fresh deploy has no datasets until a file is pushed
through the same approval-gated flow a reviewer would use.

    # The deployed secret lives in Secrets Manager; never pass it as an argument.
    export YOUTH_COMPASS_WRITE_SECRET="$(aws secretsmanager get-secret-value \
        --secret-id YouthCompass-hackathon-api-write-secret \
        --query SecretString --output text)"
    uv run python -m scripts.seed_deployed_dataset \
        --api https://<id>.execute-api.us-east-1.amazonaws.com \
        --file "data/source/01_人口/_全部年度_全區.csv" \
        --submitted-by ops --approve

The file never passes through the API: the presigned fields are posted straight
to S3, exactly as returned and with the file part last.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_TOKEN_ENV = "YOUTH_COMPASS_WRITE_SECRET"
_TOKEN_HEADER = "X-Youth-Compass-Token"
_TERMINAL = {"published", "rejected", "quarantined", "failed"}


def _client(api: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=api.rstrip("/"),
        headers={_TOKEN_HEADER: token},
        timeout=httpx.Timeout(120.0),
    )


def _at_approval_gate(job: dict[str, Any]) -> bool:
    """Distinguish the real approval gate from the initial record.

    A job is written as ``awaiting_approval`` the moment it is created, before
    the workflow has profiled anything. Approving then returns 409, because the
    Step Functions task token does not exist yet. The mapping result is what
    marks the actual gate.
    """

    return job["status"] == "awaiting_approval" and job.get("qualityScore") is not None


def _poll(client: httpx.Client, job_id: str, *, attempts: int = 120) -> dict[str, Any]:
    """Poll until the workflow settles or reaches the approval gate."""

    seen = ""
    for _ in range(attempts):
        response = client.get(f"/api/v1/ingestion-jobs/{job_id}")
        response.raise_for_status()
        job: dict[str, Any] = response.json()
        marker = f"{job['status']}/{job.get('currentStep')}"
        if marker != seen:
            seen = marker
            print(f"  status: {job['status']} (step {job.get('currentStep')})")
        if job["status"] in _TERMINAL or _at_approval_gate(job):
            return job
        time.sleep(5)
    raise SystemExit(f"job {job_id} did not settle; last status {seen!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--submitted-by", default="ops")
    parser.add_argument("--topic-hint", default=None)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve the mapping when the workflow stops for review",
    )
    args = parser.parse_args()

    token = os.environ.get(_TOKEN_ENV)
    if not token:
        raise SystemExit(f"{_TOKEN_ENV} is not set; export it and re-run")
    if not args.file.is_file():
        raise SystemExit(f"no such file: {args.file}")

    size_mb = args.file.stat().st_size / 1024 / 1024
    print(f"uploading {args.file.name} ({size_mb:.1f} MB) to {args.api}")

    with _client(args.api, token) as client:
        started = client.post(
            "/api/v1/uploads",
            json={
                "contentType": "text/csv",
                "originalFilename": args.file.name,
                "submittedBy": args.submitted_by,
            },
        )
        started.raise_for_status()
        upload = started.json()
        job_id = upload["jobId"]
        print(f"  job: {job_id}")

        # The presigned fields must be sent exactly as returned, file part last.
        with args.file.open("rb") as handle:
            posted = httpx.post(
                upload["url"],
                data=upload["fields"],
                files={"file": (args.file.name, handle, "text/csv")},
                timeout=httpx.Timeout(600.0),
            )
        if posted.status_code != 204:
            raise SystemExit(f"S3 rejected the upload: {posted.status_code} {posted.text[:300]}")
        print("  uploaded to S3")

        body: dict[str, Any] = {"objectKey": upload["objectKey"]}
        if args.topic_hint:
            body["topicHint"] = args.topic_hint
        client.post(f"/api/v1/uploads/{job_id}/complete", json=body).raise_for_status()
        print("  workflow started")

        job = _poll(client, job_id)
        if _at_approval_gate(job) and args.approve:
            print(f"  approving (quality {job.get('qualityScore')})")
            client.post(
                f"/api/v1/ingestion-jobs/{job_id}/decision",
                json={"decision": "approve", "decidedBy": args.submitted_by},
            ).raise_for_status()
            job = _poll(client, job_id)

        print(f"final status: {job['status']}")
        for warning in job.get("warnings", []):
            print(f"  warning: {warning}")
        if job["status"] != "published":
            sys.exit(1)


if __name__ == "__main__":
    main()
