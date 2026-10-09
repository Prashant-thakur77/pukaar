"""Identifier helpers."""

from __future__ import annotations

import secrets

from ulid import ULID

_TRACK_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def new_id(prefix: str) -> str:
    return f"{prefix}_{str(ULID()).lower()}"


def track_code() -> str:
    return "".join(secrets.choice(_TRACK_ALPHABET) for _ in range(6))
