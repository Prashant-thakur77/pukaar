"""Named-shadow transport: what a device reads on every connect ("siren" and "config" shadows).

AWS: AWS IoT Core's data plane (iot-data UpdateThingShadow, the ATS endpoint botocore resolves). The
callers' roles may update the shadows of siren-* and box-* things only (infra/template.yaml).
Local mode: the desired document is kept in the table (DEVICE#<d> / SHADOW#<name>), so the whole loop
runs without AWS. Tests swap the client with set_client().

The shadow is the command's single source of truth, never a QoS 1 message queue: a device does a
shadow get on every connect (a command that waited past its exp is refused by the device).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from Pukaar.core.config import get_settings


class ShadowClient(Protocol):
    def update_desired(self, thing: str, name: str, desired: dict[str, Any]) -> int | None: ...


class IotShadow:
    def __init__(self) -> None:
        import boto3

        self._c = boto3.client("iot-data", region_name=get_settings().aws_region)

    def update_desired(self, thing: str, name: str, desired: dict[str, Any]) -> int | None:
        body = json.dumps({"state": {"desired": desired}}, separators=(",", ":"))
        resp = self._c.update_thing_shadow(thingName=thing, shadowName=name, payload=body.encode("utf-8"))
        doc = json.loads(resp["payload"].read() or b"{}")
        return doc.get("version")


class LocalShadow:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    def update_desired(self, thing: str, name: str, desired: dict[str, Any]) -> int | None:
        current = self.repo.get_local_shadow(thing, name) or {"desired": {}}
        merged = {**current["desired"], **desired}
        return self.repo.put_local_shadow(thing, name, merged)


_override: ShadowClient | None = None


def set_client(client: ShadowClient | None) -> None:
    """Tests: replace the transport (None restores the default)."""
    global _override
    _override = client


def get_client(repo: Any) -> ShadowClient:
    if _override is not None:
        return _override
    if get_settings().device_shadow == "local":
        return LocalShadow(repo)
    return IotShadow()
