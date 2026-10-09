"""Local mode: an in-process AWS mock (moto) holding the table and bucket.

Lets the full loop (sweep, replay, approval, delivery records, reports) run on
a laptop or in CI with no AWS account. Bedrock, Polly and Transcribe are not
mocked: in local mode they report "unavailable" and the rule fallbacks run.
"""

from __future__ import annotations

import os

_STARTED = False


def start_local_aws() -> None:
    global _STARTED
    if _STARTED:
        return
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    from moto import mock_aws

    mock = mock_aws()
    mock.start()
    _STARTED = True

    import boto3

    from Pukaar.core.config import get_settings
    from Pukaar.store.repo import table_schema

    s = get_settings()
    boto3.client("dynamodb", region_name=s.aws_region).create_table(**table_schema(s.table_name))
    boto3.client("s3", region_name=s.aws_region).create_bucket(Bucket=s.bucket)

    from Pukaar.scripts.seed import seed
    from Pukaar.store.repo import get_repo

    seed(get_repo())
