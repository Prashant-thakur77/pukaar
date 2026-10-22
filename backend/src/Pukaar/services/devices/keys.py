"""Per-device keys: HKDF-SHA256 from one root secret, derived in memory when needed.

The root is the SSM SecureString /pukaar/device_root (32 random bytes, hex; `make secrets`). Only the
API, the approval workflow and the device-ingest path (the gauge-ingest function) may read it; the
worker is denied it explicitly and the sweep has no SSM grant at all (infra/template.yaml). A derived
key is never logged, returned on a route or written to the table.

Why not a KMS HMAC key: it bills $1 a month whether or not it is used, and the dev stack must stay free
(backend/tests/test_template_safety.py). The defence it would add over this design (the root never
leaves an HSM) is the production upgrade: derive() is the one seam, and a prod-only
AWS::KMS::Key (KeySpec HMAC_256, GenerateMac only to the same three roles) can replace the SSM root
without changing the protocol or the devices' keys' shape (docs/SECURITY.md).

Local mode and tests: PUKAAR_DEVICE_ROOT (hex or text), else one random root per process.
"""

from __future__ import annotations

from Pukaar.core.secrets import get_secret
from Pukaar.services.devices import protocol


class KeyUnavailable(RuntimeError):
    """The root secret could not be read: nothing can be signed (fail closed)."""


def root() -> bytes:
    raw = get_secret("device_root", generate_locally=True)
    if not raw:
        raise KeyUnavailable("device root secret unavailable")
    raw = raw.strip()
    try:
        value = bytes.fromhex(raw)
    except ValueError:
        value = raw.encode("utf-8")
    if len(value) < 16:
        raise KeyUnavailable("device root secret is too short")
    return value


def derive(device_id: str, kid: int = 1) -> bytes:
    return protocol.derive_device_key(root(), device_id, kid)
