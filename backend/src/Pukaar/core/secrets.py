"""Secrets from SSM Parameter Store (SecureString). Local mode uses env vars or
a per-process random value; nothing secret is ever committed or put in the
SAM template."""

from __future__ import annotations

import os
import secrets as pysecrets
from functools import lru_cache

from Pukaar.core.config import get_settings

_LOCAL_RANDOM: dict[str, str] = {}


@lru_cache(maxsize=16)
def _ssm(name: str) -> str | None:
    import boto3

    s = get_settings()
    try:
        resp = boto3.client("ssm", region_name=s.aws_region).get_parameter(Name=f"{s.ssm_prefix}/{name}", WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        return None


def get_secret(name: str, *, generate_locally: bool = False) -> str | None:
    """name is one of telegram_token, telegram_webhook_secret, link_secret."""
    env = os.environ.get(f"PUKAAR_{name.upper()}")
    if env:
        return env
    if get_settings().is_local:
        if generate_locally:
            return _LOCAL_RANDOM.setdefault(name, pysecrets.token_urlsafe(32))
        return None
    return _ssm(name)
