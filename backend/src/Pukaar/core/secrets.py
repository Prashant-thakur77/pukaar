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
    except Exception as exc:
        # None means "unavailable", not "configured as empty". Callers that send (delivery,
        # roll-call) record a failure with this reason; they never fall back to a stub.
        from Pukaar.core.log import get_logger, log, metric

        not_found = "ParameterNotFound" in f"{type(exc).__name__} {exc}"
        log(get_logger("secrets"), "secret not set" if not_found else "secret read failed", 30 if not_found else 40,
            name=name, error=type(exc).__name__)
        if not not_found:
            metric("SecretReadFailed", 1)
        return None
    value = resp["Parameter"]["Value"]
    _CACHE[name] = (time.monotonic(), value)
    return value


def get_secret(name: str, *, generate_locally: bool = False) -> str | None:
    """name is one of telegram_token, telegram_webhook_secret, link_secret, after_action_to,
    vapid_private_key (SecureString) or vapid_public_key (String; scripts/vapid_keys.py), and for
    voice calls (docs/VOICE.md): voice_webhook_key, exotel_sid, exotel_api_key, exotel_token,
    exotel_caller_id, exotel_app_id, plivo_auth_id, plivo_auth_token, plivo_caller_id."""
    env = os.environ.get(f"PUKAAR_{name.upper()}")
    if env:
        return env
    if get_settings().is_local:
        if generate_locally:
            return _LOCAL_RANDOM.setdefault(name, pysecrets.token_urlsafe(32))
        return None
    return _ssm(name)
