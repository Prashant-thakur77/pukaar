"""Make the VAPID key pair for Web Push and store it in SSM (run once, via `make vapid-keys`).

    python -m Pukaar.scripts.vapid_keys            # keep an existing pair
    python -m Pukaar.scripts.vapid_keys --rotate   # replace it (every phone must turn alerts on again)

A P-256 key pair is generated in this process. The private key (32-byte scalar, base64url) goes
to SSM SecureString /pukaar/vapid_private_key and the public key (65-byte uncompressed point,
base64url) to String /pukaar/vapid_public_key. Like scripts/iot_provision.py, the private key
exists only in this process's memory and in SSM: boto3 sends it in the request body, so it is
never on a command line, in a file or in the output. The AWS CLI route in scripts/put_secrets.sh
needs its /dev/shm file only because the CLI cannot read the JSON from a pipe.

The Lambdas read both with core/secrets.get_secret; nothing goes in the SAM template or env.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

PRIVATE = "vapid_private_key"
PUBLIC = "vapid_public_key"


def _get(ssm: Any, name: str) -> str | None:
    try:
        return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None


def ensure_keys(ssm: Any, prefix: str = "/pukaar", rotate: bool = False) -> tuple[str, bool]:
    """Returns (public key, created). An existing matching pair is kept unless rotate."""
    from Pukaar.delivery import webpush

    priv_name, pub_name = f"{prefix}/{PRIVATE}", f"{prefix}/{PUBLIC}"
    if not rotate:
        priv, pub = _get(ssm, priv_name), _get(ssm, pub_name)
        if priv and pub:
            try:
                if webpush.public_key_text(webpush.private_key_from_text(priv)) == pub:
                    return pub, False
            except (webpush.PushError, ValueError):
                pass
            print("existing VAPID parameters do not match; making a new pair", file=sys.stderr)
    priv, pub = webpush.generate_keys()
    # Private first: until the public key is replaced too, the API treats the pair as not set up
    # (services/officer_push.vapid_keys checks they match), never as a wrong key.
    ssm.put_parameter(Name=priv_name, Value=priv, Type="SecureString", Overwrite=True,
                      Description="Pukaar Web Push VAPID private key (P-256 scalar, base64url)")
    ssm.put_parameter(Name=pub_name, Value=pub, Type="String", Overwrite=True,
                      Description="Pukaar Web Push VAPID public key (uncompressed P-256 point, base64url)")
    return pub, True


def main(argv: list[str] | None = None) -> int:
    import boto3

    from Pukaar.core.config import get_settings

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rotate", action="store_true", help="replace an existing pair; phones must subscribe again")
    args = p.parse_args(argv)
    s = get_settings()
    ssm = boto3.client("ssm", region_name=s.aws_region)
    pub, created = ensure_keys(ssm, s.ssm_prefix, rotate=args.rotate)
    if created:
        print(f"stored {s.ssm_prefix}/{PRIVATE} (SecureString, not shown)")
        print(f"stored {s.ssm_prefix}/{PUBLIC}")
    else:
        print(f"kept {s.ssm_prefix}/{PRIVATE} and {s.ssm_prefix}/{PUBLIC} (use ROTATE=1 to replace them)")
    print(f"public key: {pub}")
    if args.rotate:
        print("Rotated: every officer must open the console and turn approval alerts on again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
