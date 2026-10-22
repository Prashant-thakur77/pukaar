"""Device messages over AWS IoT Core: sirens, pradhan boxes, LoRa relays and rain-only nodes.

The gauge-ingest Lambda runs this (handlers/gauge_ingest.handler dispatches here): one function, one
image, one DLQ for every device (infra/template.yaml). Three topic rules feed it:

  pukaar_device_<stage>    SELECT *, topic(2) AS device_kind, topic(3) AS village_id, topic(4) AS device_id,
                           topic(5) AS topic_kind FROM 'pukaar/+/+/+/+' WHERE (siren|box|mesh) AND
                           (event|heartbeat|backfill|relay)   ("device_kind", not "kind": a test_result
                           event carries its own "kind", silent or audible)
      pukaar/siren/<village>/<device>/event       one event (the envelope in docs/CONTRACT.md)
      pukaar/siren/<village>/<device>/heartbeat   every 5 minutes (15 in the low-SoC tier)
      pukaar/siren/<village>/<device>/backfill    {"events": [...]}, up to 30, from the device's outbox
      pukaar/box/<village>/<device>/...           the same for a pradhan box
      pukaar/mesh/<village>/<forwarder>/relay     {"frames": ["<base64 LoRa frame>", ...]} heard on LoRa
  pukaar_device_presence_<stage>   $aws/events/presence/+/+ for siren-, box- and relay- clients
  pukaar_siren_shadow_<stage>      $aws/things/+/shadow/name/siren/update/documents (reported state)

The topic is the identity (the IoT policy pins it to the certificate's thing), and the device must be
registered for that village with that kind. Events are idempotent on (device, boot, seq). A live event
must be stamped within WINDOW_SECONDS of now; history comes through /backfill. A frame forwarded over
LoRa is checked with its ORIGIN's key (a forwarder holds no sender keys and cannot forge one), and its
counter must be above the last one heard from that origin.

A message that can never be stored is logged and returned as "rejected" (no retry); anything else
(DynamoDB unavailable) raises and the asynchronous invocation lands in the DLQ.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from boto3.dynamodb.conditions import Attr
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.services import rain_obs, sirens
from Pukaar.services.devices import keys, protocol, registry
from Pukaar.store.models import Device
from Pukaar.store.repo import ConflictError, Repo, get_repo

_LOG = get_logger("handler.device_ingest")
WINDOW_SECONDS = 600
BACKFILL_MAX_HOURS = 72
BACKFILL_MAX_ITEMS = 30
FRAMES_MAX = 30
KINDS = {"siren", "box", "mesh"}
TOPIC_KINDS = {"event", "heartbeat", "backfill", "relay"}
EVENT_TYPES = tuple(protocol.EVENT_CODES)
ID = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


class DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    v: int = Field(default=1, ge=1, le=3)
    seq: int = Field(ge=0, le=4_294_967_295)
    boot: int = Field(default=0, ge=0, le=4_294_967_295)
    at: str = Field(max_length=40)
    type: Literal[EVENT_TYPES]  # type: ignore[valid-type]
    cmd_id: str | None = Field(default=None, max_length=64)
    pattern: str | None = Field(default=None, max_length=8)
    via: Literal["mqtt", "sms", "lora"] | None = None
    src: str | None = Field(default=None, max_length=24)
    meas: dict[str, float | int] | None = None
    reason: str | None = Field(default=None, max_length=60)
    button: str | None = Field(default=None, max_length=24)
    level: Literal["warning", "critical"] | None = None
    frame_src: str | None = Field(default=None, max_length=64)
    kind: Literal["silent", "audible", "pour"] | None = None
    ok: bool | None = None
    detail: str | None = Field(default=None, max_length=200)
    faults: list[str] | None = Field(default=None, max_length=16)
    lora_acked: bool | None = None
    simulated: bool = False


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    v: int = Field(default=1, ge=1, le=3)
    at: str = Field(max_length=40)
    seq: int | None = Field(default=None, ge=0)
    boot: int | None = Field(default=None, ge=0)
    state: str | None = Field(default=None, max_length=16)
    soc: int | None = Field(default=None, ge=0, le=100)
    batt_mv: int | None = Field(default=None, ge=0, le=30_000)
    solar_wh_today: float | None = Field(default=None, ge=0, le=10_000)
    temp_c: float | None = Field(default=None, ge=-50, le=90)
    rssi: int | None = Field(default=None, ge=-150, le=0)
    lora_noise_dbm: int | None = Field(default=None, ge=-160, le=0)
    fw: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9_.+-]+$")
    clips: str | None = Field(default=None, max_length=32)
    uptime_s: int | None = Field(default=None, ge=0)
    outbox_depth: int | None = Field(default=None, ge=0, le=1_000_000)
    faults: list[str] | None = Field(default=None, max_length=16)
    path: Literal["cell", "lora", "sms"] | None = None
    simulated: bool = False


class TopicIds(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_kind: Literal["siren", "box", "mesh"]
    village_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    device_id: str = ID
    topic_kind: Literal["event", "heartbeat", "backfill", "relay"]


def is_device_message(event: Any) -> bool:
    """For the gauge-ingest handler: a message for this module (device topics, presence, siren shadow)."""
    if not isinstance(event, dict):
        return False
    if event.get("device_kind") in KINDS:
        return True
    if "eventType" in event and "clientId" in event:
        return True
    return event.get("source") == "siren_shadow"


def _reject(code: str, reason: str, event: dict[str, Any]) -> dict[str, Any]:
    log(_LOG, "device message rejected", 30, code=code, reason=reason[:300],
        village_id=str(event.get("village_id", ""))[:64], device_id=str(event.get("device_id", ""))[:64])
    metric("DeviceRejected", 1, Reason=code)
    return {"status": "rejected", "code": code, "reason": reason}


def _registered(repo: Repo, village_id: str, device_id: str, kinds: set[str]) -> Device | None:
    d = repo.get_device(device_id)
    if d is None or d.village_id != village_id or d.kind not in kinds:
        return None
    return d


def handle(event: Any, repo: Repo | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return _reject("bad_payload", "payload is not a JSON object", {})
    repo = repo or get_repo()
    now = now or clock.now()
    if "eventType" in event and "clientId" in event:
        return _presence(repo, event, now)
    if event.get("source") == "siren_shadow":
        return _shadow(repo, event, now)
    try:
        ids = TopicIds.model_validate(event)
    except ValidationError as exc:
        return _reject("bad_topic", str(exc)[:200], event)
    if ids.device_kind == "mesh":
        if ids.topic_kind != "relay":
            return _reject("bad_topic", "a mesh topic ends in /relay", event)
        forwarder = _registered(repo, ids.village_id, ids.device_id, {"box", "relay", "siren", "gauge"})
        if forwarder is None:
            return _reject("wrong_device", "the forwarder is not registered for this village", event)
        return _relay(repo, forwarder, event, now)
    d = _registered(repo, ids.village_id, ids.device_id, {ids.device_kind})
    if d is None:
        return _reject("wrong_device", f"{ids.device_id} is not a registered {ids.device_kind} of {ids.village_id}",
                       event)
    if event.get("simulated") is True and not d.simulated:
        return _reject("simulated", "a simulated payload from a device registered as real hardware", event)
    if ids.topic_kind == "heartbeat":
        return _heartbeat(repo, d, event, now)
    if ids.topic_kind == "event":
        return _event(repo, d, event, now, live=True)
    if ids.topic_kind == "backfill":
        items = event.get("events")
        if not isinstance(items, list) or not items:
            return _reject("bad_payload", "backfill needs a non-empty events list", event)
        if len(items) > BACKFILL_MAX_ITEMS:
            return _reject("too_many", f"at most {BACKFILL_MAX_ITEMS} events per backfill message", event)
        results = [_event(repo, d, item if isinstance(item, dict) else {}, now, live=False) for item in items]
        return {"status": "accepted", "kind": "backfill",
                "stored": sum(1 for r in results if r.get("status") == "accepted"),
                "duplicate": sum(1 for r in results if r.get("status") == "duplicate"),
                "rejected": [r for r in results if r.get("status") == "rejected"]}
    return _reject("bad_topic", "unknown topic kind", event)


def _event(repo: Repo, d: Device, raw: dict[str, Any], now: datetime, *, live: bool) -> dict[str, Any]:
    try:
        ev = DeviceEvent.model_validate(raw)
        at = clock.parse(ev.at)
    except (ValueError, ValidationError) as exc:
        return _reject("bad_payload", str(exc)[:200], {"device_id": d.device_id, "village_id": d.village_id})
    age = (now - at).total_seconds()
    if live and abs(age) > WINDOW_SECONDS:
        return _reject("stale", f"a live event must be within {WINDOW_SECONDS // 60} minutes of now; "
                                "history goes to /backfill", {"device_id": d.device_id})
    if not live and (age > BACKFILL_MAX_HOURS * 3600 or age < -WINDOW_SECONDS):
        return _reject("stale", f"outside the {BACKFILL_MAX_HOURS} h backfill window", {"device_id": d.device_id})
    if not repo.claim_device_seq(d.device_id, ev.boot, ev.seq):
        return {"status": "duplicate", "seq": ev.seq, "boot": ev.boot}
    body = ev.model_dump(exclude_none=True)
    repo.put_device_event(d.device_id, clock.iso(at), ev.boot, ev.seq, {**body, "live": live})
    out = sirens.on_event(repo, repo.get_device(d.device_id) or d, body, via="cell", now=now, live=live)
    log(_LOG, "device event", device_id=d.device_id, type=ev.type, live=live, cmd_id=ev.cmd_id)
    return {"status": "accepted", **{k: v for k, v in out.items() if v is not None}}


def _heartbeat(repo: Repo, d: Device, raw: dict[str, Any], now: datetime) -> dict[str, Any]:
    try:
        hb = Heartbeat.model_validate(raw)
        at = clock.parse(hb.at)
    except (ValueError, ValidationError) as exc:
        return _reject("bad_payload", str(exc)[:200], raw)
    if abs((now - at).total_seconds()) > WINDOW_SECONDS:
        return _reject("stale", "heartbeat timestamp too far from now", raw)
    updated = registry.apply_heartbeat(repo, d, hb.model_dump(exclude_none=True), clock.iso(at), path=hb.path or "cell")
    return {"status": "accepted" if updated else "ignored", "kind": "heartbeat"}


def _presence(repo: Repo, event: dict[str, Any], now: datetime) -> dict[str, Any]:
    client = str(event.get("clientId", ""))[:64]
    d = repo.get_device(client)
    if d is None or not client.startswith(("siren-", "box-", "relay-")):
        return _reject("wrong_device", "presence from an unregistered client", {"device_id": client})
    connected = event.get("eventType") == "connected"
    ts = event.get("timestamp")
    at = clock.iso(datetime.fromtimestamp(int(ts) / 1000, tz=now.tzinfo)) if isinstance(ts, (int, float)) else clock.iso(now)
    version = event.get("versionNumber") if isinstance(event.get("versionNumber"), int) else None
    registry.apply_presence(repo, d, connected, at, version)
    return {"status": "accepted", "kind": "presence", "connected": connected}


def _shadow(repo: Repo, event: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The siren shadow's reported state (update/documents): the device's own word for its state."""
    thing = str(event.get("thing_name", ""))[:64]
    d = repo.get_device(thing)
    if d is None:
        return _reject("wrong_device", "shadow of an unregistered thing", {"device_id": thing})
    reported = ((event.get("current") or {}).get("state") or {}).get("reported") or {}
    if not isinstance(reported, dict):
        return _reject("bad_payload", "no reported state", {"device_id": thing})
    fields: dict[str, Any] = {}
    state = reported.get("state")
    if isinstance(state, str) and state in protocol.STATE_CODES:
        fields["state"] = state
        if state != d.state:
            fields["state_since"] = clock.iso(now)
    for key, kind in (("fw", str), ("soc", int)):
        if isinstance(reported.get(key), kind):
            fields[key] = reported[key]
    if isinstance(reported.get("faults"), list):
        fields["faults"] = [str(f)[:24] for f in reported["faults"]][:16]
    if fields:
        repo.update_device(d.village_id, d.device_id, **fields)
    return {"status": "accepted", "kind": "shadow", "fields": sorted(fields)}


# -- LoRa frames forwarded by a box, a relay, a gauge or a siren ----------------------------------------
def _relay(repo: Repo, forwarder: Device, event: dict[str, Any], now: datetime) -> dict[str, Any]:
    frames = event.get("frames")
    if not isinstance(frames, list) or not frames or len(frames) > FRAMES_MAX:
        return _reject("bad_payload", f"relay needs 1 to {FRAMES_MAX} frames", event)
    by_addr = {d.lora_addr: d for d in repo.list_devices() if d.lora_addr is not None}
    accepted, rejected = 0, []
    for raw in frames:
        try:
            data = base64.b64decode(str(raw), validate=True)
        except (binascii.Error, ValueError):
            rejected.append("not_base64")
            continue
        ok, reason = _frame(repo, forwarder, by_addr, data, now)
        if ok:
            accepted += 1
        else:
            rejected.append(reason)
            metric("DeviceRejected", 1, Reason=f"lora_{reason}")
    log(_LOG, "mesh relay", forwarder=forwarder.device_id, accepted=accepted, rejected=len(rejected))
    return {"status": "accepted", "kind": "relay", "accepted": accepted, "rejected": rejected}


def _frame(repo: Repo, forwarder: Device, by_addr: dict[int | None, Device], data: bytes,
           now: datetime) -> tuple[bool, str]:
    try:
        frame = protocol.decode_frame(data)
    except protocol.ProtocolError:
        return False, "malformed"
    origin = by_addr.get(frame.src)
    if origin is None:
        return False, "unknown_src"
    if not protocol.frame_mac_ok(frame, keys.derive(origin.device_id, origin.kid)):
        return False, "bad_mac"  # forged, or damaged: a forwarder cannot sign for the origin
    if frame.ts and abs(frame.ts - now.timestamp()) >= 900:
        return False, "clock_skew"
    try:  # the origin's LoRa counter only goes up (persisted on the registry row)
        repo.update_device(origin.village_id, origin.device_id,
                           condition=Attr("lora_ctr").not_exists() | Attr("lora_ctr").lt(frame.ctr), lora_ctr=frame.ctr)
    except ConflictError:
        return False, "replayed"
    at = clock.iso(datetime.fromtimestamp(frame.ts, tz=now.tzinfo)) if frame.ts else clock.iso(now)
    try:
        fields = protocol.unpack_payload(frame.type, frame.payload)
    except protocol.ProtocolError:
        return False, "malformed"
    ftype = protocol.FrameType(frame.type)
    if ftype == protocol.FrameType.HEARTBEAT:
        state = {v: k for k, v in protocol.STATE_CODES.items()}.get(fields["state"])
        registry.apply_heartbeat(repo, origin, {"soc": fields["soc"], "batt_mv": fields["batt_dv"] * 100,
                                                "outbox_depth": fields["outbox"], "state": state}, at, path="lora")
    elif ftype == protocol.FrameType.RELAY_BEACON:
        registry.apply_heartbeat(repo, origin, {"soc": fields["soc"], "batt_mv": fields["bus_dv"] * 100,
                                                "lora_noise_dbm": fields["noise_dbm"]}, at, path="lora")
    elif ftype == protocol.FrameType.SIREN_EVENT:
        etype = {v: k for k, v in protocol.EVENT_CODES.items()}.get(fields["type"])
        cmd = next((c for c in repo.list_commands(origin.device_id, limit=20)
                    if protocol.cmd_id48(c.id) == fields["cmd_id48"]), None)
        if etype and cmd:
            sirens.on_event(repo, origin, {"type": etype, "cmd_id": cmd.id, "at": at,
                                           "meas": {"amp_a": fields["amp_a_x10"] / 10, "spl_rise_db": fields["spl_rise_db"]}},
                            via="lora", now=now)
    elif ftype == protocol.FrameType.BUTTON and origin.kind == "box":
        button = {v: k for k, v in protocol.BUTTON_CODES.items()}.get(fields["button"])
        key = {v: k for k, v in protocol.KEY_POS_CODES.items()}.get(fields["key_pos"], "off")
        if button == "siren" and key in {"warning", "critical"} and fields["hold_ms"] >= 3000:
            sirens.on_event(repo, origin, {"type": "manual_trigger", "button": f"key_{key}", "at": at,
                                           "lora_acked": False}, via="lora", now=now)
    repo.put_device_event(origin.device_id, at, 0, frame.ctr,
                          {"type": f"lora_{ftype.name.lower()}", "forwarder": forwarder.device_id, "ctr": frame.ctr,
                           "fields": {k: (v.hex() if isinstance(v, bytes) else v) for k, v in fields.items()}})
    registry.touch(repo, origin.village_id, origin.device_id, at, "lora")
    return True, "ok"


# -- rain-only nodes (the gauge topic, no river measurement) -----------------------------------------------
def is_rain_node(repo: Repo, event: dict[str, Any]) -> Device | None:
    device_id = str(event.get("device_id", ""))
    if not device_id.startswith("rain-"):
        return None
    return _registered(repo, str(event.get("village_id", "")), device_id, {"rain"})


def rain_node(repo: Repo, d: Device, event: dict[str, Any], now: datetime) -> dict[str, Any]:
    """A rain node's reading (live, or a backfill of buffered ones): observed rain only."""
    village = repo.get_village(d.village_id)
    if village is None:
        return _reject("not_found", "village not found", event)
    kind = event.get("topic_kind", "reading")
    items = event.get("readings") if kind == "backfill" else [event]
    if not isinstance(items, list) or not items or len(items) > 60:
        return _reject("bad_payload", "a backfill needs 1 to 60 readings", event)
    stored, levels = 0, []
    for item in items:
        try:
            fields = rain_obs.RainFields.model_validate(item)
            at = clock.parse(fields.at)
        except (ValueError, ValidationError) as exc:
            return _reject("bad_payload", str(exc)[:200], event)
        if fields.simulated and not d.simulated:
            return _reject("simulated", "a simulated payload from a device registered as real hardware", event)
        origin = "backfill" if (kind == "backfill" or fields.buffered) else "live"
        age = (now - at).total_seconds()
        if origin == "live" and abs(age) > WINDOW_SECONDS:
            return _reject("stale", "a live reading must be within 10 minutes of now", event)
        if origin == "backfill" and not (-WINDOW_SECONDS <= age <= BACKFILL_MAX_HOURS * 3600):
            continue
        r = rain_obs.ingest(repo, village, d.device_id, fields, at, now=now, transport="mqtt", origin=origin,
                            source="rain_node")
        if r is not None:
            stored += 1
            levels.append(r.eval_level if origin == "live" else "normal")
    registry.touch(repo, d.village_id, d.device_id, clock.iso(now), "cell")
    top = max(levels, key=lambda lvl: ["normal", "watch", "warning", "critical"].index(lvl), default="normal")
    out: dict[str, Any] = {"status": "accepted", "kind": "rain", "stored": stored, "rain_level": top}
    if top != "normal" and not d.simulated:  # Watch or above re-runs the village's rules at once, only to raise
        from Pukaar.services.decision_engine import recompute_village
        from Pukaar.workflow.client import get_workflow

        try:
            res = recompute_village(repo, village, now=now, workflow=get_workflow(), only_if_rising=True)
            out.update(village_level=res.level, alert_id=res.alert_id)
        except Exception as exc:
            log(_LOG, "recompute after rain failed", 40, village_id=village.id, error=str(exc)[:200])
    return out
