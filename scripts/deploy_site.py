"""Publish the static frontend to the site bucket and invalidate CloudFront.

Reads the bucket name, distribution id, and API base URL from the deployed
ApiStack outputs, so there is nothing to keep in sync by hand:

    uv run python -m scripts.deploy_site
    uv run python -m scripts.deploy_site --source path/to/frontend/dist

The API base URL is injected into the page as ``window.YOUTH_COMPASS_API_BASE``,
which lets the same build artifact target any deployment.
"""

import argparse
import mimetypes
import sys
import time
from pathlib import Path

import boto3

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE = _REPO_ROOT / "web"
_STACK_SUFFIX = "-Api"

# Long-lived assets are safe to cache; the entry document must not be, or a
# deploy would not be visible until the old copy expired.
_NO_CACHE = "no-cache, no-store, must-revalidate"
_IMMUTABLE = "public, max-age=31536000, immutable"
_ENTRY_DOCUMENTS = {"index.html", "404.html"}


def _api_v1_base(api_base: str) -> str:
    """Return the versioned API root expected by the frontend client."""

    root = api_base.rstrip("/")
    return root if root.endswith("/api/v1") else f"{root}/api/v1"


def _outputs(stack_name: str, region: str) -> dict[str, str]:
    client = boto3.client("cloudformation", region_name=region)
    stacks = client.describe_stacks(StackName=stack_name)["Stacks"]
    return {
        output["OutputKey"]: output["OutputValue"]
        for output in stacks[0].get("Outputs", [])
        if "OutputKey" in output and "OutputValue" in output
    }


def _render(path: Path, api_base: str) -> bytes:
    """Inject the deployed API base URL into an HTML entry document."""
    content = path.read_bytes()
    if path.suffix.lower() != ".html":
        return content
    text = content.decode("utf-8")
    text = text.replace("__API_BASE_URL__", api_base)
    if "YOUTH_COMPASS_API_BASE" not in text.split("<script>")[0]:
        text = text.replace(
            "<script>",
            f'<script>window.YOUTH_COMPASS_API_BASE = "{api_base}";</script>\n    <script>',
            1,
        )
    return text.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument("--env", default="hackathon")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    source: Path = args.source
    if not source.is_dir():
        print(f"source directory does not exist: {source}", file=sys.stderr)
        return 1

    stack_name = f"YouthCompass-{args.env}{_STACK_SUFFIX}"
    outputs = _outputs(stack_name, args.region)
    bucket = outputs["SiteBucketName"]
    distribution_id = outputs["DistributionId"]
    api_base = _api_v1_base(outputs["ApiBaseUrl"])

    s3 = boto3.client("s3", region_name=args.region)
    uploaded = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        key = str(path.relative_to(source)).replace("\\", "/")
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=_render(path, api_base),
            ContentType=content_type,
            CacheControl=_NO_CACHE if path.name in _ENTRY_DOCUMENTS else _IMMUTABLE,
        )
        uploaded += 1
        print(f"  uploaded {key}")

    cloudfront = boto3.client("cloudfront", region_name=args.region)
    invalidation = cloudfront.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": f"deploy-site-{int(time.time())}",
        },
    )
    print(f"uploaded {uploaded} file(s) to s3://{bucket}")
    print(f"invalidated {distribution_id}: {invalidation['Invalidation']['Id']}")
    print(f"site: {outputs['SiteUrl']}")
    print(f"api : {api_base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
