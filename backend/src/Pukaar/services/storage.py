"""Audio, photos and replay files in S3, read back through presigned URLs.

In local mode the bucket lives in the in-process moto mock, so URLs point at
the API's /media route instead of S3.
"""

from __future__ import annotations

from functools import lru_cache

import boto3

from Pukaar.core.config import get_settings

# Lambda takes at most 6 MB per request and multipart arrives base64-encoded.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3", region_name=get_settings().aws_region)


def put_bytes(key: str, data: bytes, content_type: str) -> str:
    _s3().put_object(Bucket=get_settings().bucket, Key=key, Body=data, ContentType=content_type)
    return key


def get_bytes(key: str) -> tuple[bytes, str]:
    obj = _s3().get_object(Bucket=get_settings().bucket, Key=key)
    return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")


def url_for(key: str | None, expires: int = 3600) -> str | None:
    if not key:
        return None
    s = get_settings()
    if s.is_local:
        return f"{s.api_url}/media/{key}"
    return _s3().generate_presigned_url("get_object", Params={"Bucket": s.bucket, "Key": key}, ExpiresIn=expires)


def s3_uri(key: str) -> str:
    return f"s3://{get_settings().bucket}/{key}"
