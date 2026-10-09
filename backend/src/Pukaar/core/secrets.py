"""Secrets from SSM Parameter Store (SecureString). Local mode uses env vars or
a per-process random value; nothing secret is ever committed or put in the
SAM template."""

from __future__ import annotations

import os
import secrets as pysecrets

from Pukaar.core.config import get_settings

_LOCAL_RANDOM: dict[str, str] = {}


_CACHE: dict[str, tuple[float, str]] = {}
_TTL_SECONDS = 300


def _ssm(name: str) -> str | None:
    """Successful reads are cached for 5 minutes; failures are never cached."""
    import time

    import boto3

    hit = _CACHE.get(name)
    if hit and time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    s = get_settings()
    try:
        resp = boto3.client("ssm", region_name=s.aws_region).get_parameter(Name=f"{s.ssm_prefix}/{name}", WithDecryption=True)
    except Exception:
        return None
    value = resp["Parameter"]["Value"]
    _CACHE[name] = (time.monotonic(), value)
    return value


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
