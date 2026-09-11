"""S3 ObjectStore binding for the contract suite under moto.

Wraps ``mock_aws`` so every boto3 call routes to moto. Registers as
``s3-moto`` — the contract class body is unchanged.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.s3_store import S3ObjectStore
from tests.contract.registry import register_object_store

_BUCKET = "contract-test-bucket"
_REGION = "ap-northeast-1"


@register_object_store("s3-moto")
@contextmanager
def _s3_object_store() -> Iterator[S3ObjectStore]:
    with mock_aws():
        s3 = boto3.client("s3", region_name=_REGION)
        s3.create_bucket(
            Bucket=_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": _REGION},
        )
        yield S3ObjectStore(bucket=_BUCKET, region=_REGION)
