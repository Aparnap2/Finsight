"""Idempotent MiniStack S3 resource initialization for contract tests.

Creates only the resources justified by the seam audit:
  - finsight-evidence-test
  - finsight-legacy-outbound-test
  - finsight-legacy-result-test

Idempotent: running twice does not corrupt or duplicate resources.
Uses shared/aws/config.py for endpoint selection; test credentials only.
"""

from __future__ import annotations

import logging
import sys

from shared.aws.config import get_aws_settings

logger = logging.getLogger(__name__)

BUCKETS = [
    get_aws_settings().s3_evidence_bucket,
    get_aws_settings().s3_legacy_outbound_bucket,
    get_aws_settings().s3_legacy_result_bucket,
]


def init_buckets() -> None:
    """Create required S3 buckets idempotently; exits 0 ok, 1 config, 2 connection error."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        logger.error(
            "boto3 not installed — run: uv sync --group ministack  (or uv pip install boto3)"
        )
        sys.exit(1)

    settings = get_aws_settings()
    endpoint = settings.aws_endpoint_url
    region = settings.aws_region

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    except Exception as exc:
        logger.error("Failed to create S3 client for %s: %s", endpoint, exc)
        sys.exit(2)

    for bucket in BUCKETS:
        try:
            # Idempotent: check existence first to avoid noisy error on re-run
            s3.head_bucket(Bucket=bucket)
            logger.info("Bucket already exists: %s", bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                try:
                    if region == "us-east-1":
                        s3.create_bucket(Bucket=bucket)
                    else:
                        s3.create_bucket(
                            Bucket=bucket,
                            CreateBucketConfiguration={"LocationConstraint": region},
                        )
                    logger.info("Created bucket: %s", bucket)
                except ClientError as create_exc:
                    # Race-safe: bucket created between head and create
                    if (
                        create_exc.response.get("Error", {}).get("Code")
                        == "BucketAlreadyOwnedByYou"
                    ):
                        logger.info("Bucket already exists (race): %s", bucket)
                    else:
                        raise
            else:
                raise

    logger.info("MiniStack init complete: %d buckets ready at %s", len(BUCKETS), endpoint)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_buckets()
