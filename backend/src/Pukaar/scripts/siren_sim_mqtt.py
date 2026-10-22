"""Siren SIMULATOR over MQTT: a terminal siren node on the real AWS IoT Core, as the labelled "-sim" thing.

This is not hardware and never claims to be: it refuses any device id that does not end in "-sim", and
every event and heartbeat it sends carries "simulated": true. It does what the siren firmware will do
(docs/hardware/ALARM.md), with the same checks (services/devices/siren_model.py) and the same codec as
the firmware's golden vectors (services/devices/protocol.py):

- connects with the thing's own X.509 certificate (`make device-provision KIND=siren VILLAGE=thunag`
  stores it in SSM with the simulator's signing key), subscribes to its named shadow "siren", and asks
  for the shadow at once (a device never relies on queued messages);
- for each desired.cmd: verifies the signature, the counter and the expiry, prints the pattern and what a
  node would measure ("W1 ... verified 3.1 A +24 dB"), and publishes cmd_received, started and verified
  (or rejected with the reason) to pukaar/siren/<village>/<device>/event, then its reported state;
- sends a heartbeat every --heartbeat seconds (5 minutes by default).

    python -m Pukaar.scripts.siren_sim_mqtt thunag             # via `make siren-sim VILLAGE=thunag`
    python -m Pukaar.scripts.siren_sim_mqtt thunag --fault mic_dead
    python -m Pukaar.scripts.siren_sim_mqtt thunag --offline 600   # stay silent first (SirenOffline after 20 min)
    python -m Pukaar.scripts.siren_sim_mqtt thunag --sms "PKR1 siren-thunag-sim SW 000413 ..."   # check one SMS

Faults: amp_open (no current: never verified), mic_dead (current only: verified, flagged), battery_low
(SoC 22 %), tamper (a tamper event at start). The LoRa path (--lora-from) comes with the firmware (slice M).
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any, Callable

from Pukaar.core import clock
from Pukaar.scripts.gauge_sim_mqtt import ROOT_CA_URL, _secret_dir, _write_private
from Pukaar.scripts.iot_provision import REGION, ats_endpoint, hmac_param, param_names
from Pukaar.services.devices import protocol
from Pukaar.services.devices.siren_model import CommandVerifier, is_verified

FW = "pukaar-siren-sim-1.0.0"
TONE = {"W1": "3 x (5 s steady 650 Hz, 3 s off), then the Hindi warning clip",
        "C1": "60 s rising and falling 500-1050 Hz, then the Hindi danger clip",
        "A1": "30 s steady 650 Hz, then the all-clear clip", "T1": "3 short beeps at 900 Hz, then the test clip",
        "D1": "the drill clip first, one W1 cycle, then 'यह अभ्यास था'"}


def measurements(fault: str | None, test_silent: bool = False) -> dict[str, Any]:
    """What a node would measure during the first tone (plausible, labelled simulated)."""
    if fault == "amp_open":
        return {"amp_a": 0.1, "amp_a_ref": 3.3, "spl_rise_db": 0.5, "siren_a": 0.0}
    meas = {"amp_a": 3.1, "amp_a_ref": 3.3, "siren_a": 1.4, "spl_rise_db": 24.5, "ambient_db_rel": -31.0}
    if fault == "mic_dead":
        meas.pop("spl_rise_db")
    if test_silent:  # into the dummy load: current only, the horns stay quiet
        meas = {"amp_a": 3.0, "amp_a_ref": 3.3}
    return meas


class Node:
    """The simulated siren's state: its verifier (counters, recent ids), sequence numbers and soc."""

    def __init__(self, village: str, device: str, key: bytes, fault: str | None,
                 send: Callable[[str, dict[str, Any]], None]) -> None:
        self.village, self.device, self.fault, self.send = village, device, fault, send
        self.verifier = CommandVerifier(device, {1: key})
        self.boot = int(time.time()) % 1_000_000
        self.seq = 0
        self.state = "idle"
        self.soc = 22 if fault == "battery_low" else 86

    def topic(self, kind: str) -> str:
        return f"pukaar/siren/{self.village}/{self.device}/{kind}"

    def event(self, etype: str, **fields: Any) -> None:
        self.seq += 1
        body = {"v": 1, "seq": self.seq, "boot": self.boot, "at": clock.iso(datetime.now(UTC)), "type": etype,
                "simulated": True, **{k: v for k, v in fields.items() if v is not None}}
        self.send(self.topic("event"), body)

    def heartbeat(self) -> None:
        self.send(self.topic("heartbeat"), {
            "v": 1, "at": clock.iso(datetime.now(UTC)), "seq": self.seq, "boot": self.boot, "state": self.state,
            "soc": self.soc, "batt_mv": 13180 if self.soc > 30 else 12650, "solar_wh_today": 41.5, "temp_c": 17.0,
            "rssi": -79, "lora_noise_dbm": -118, "fw": FW, "clips": "catalog-sim", "uptime_s": int(time.monotonic()),
            "outbox_depth": 0, "faults": [self.fault] if self.fault in {"mic_dead", "amp_open"} else [],
            "path": "cell", "simulated": True})

    def command(self, cmd: dict[str, Any]) -> None:
        ok, reason = self.verifier.accept(cmd, "mqtt", int(time.time()))
        pattern, cid = cmd.get("pattern") or "-", cmd.get("id")
        if not ok:
            print(f"  REJECTED {cid} ({cmd.get('action')} {pattern}): {reason}")
            self.event("rejected", cmd_id=cid, reason=reason, via="mqtt")
            return
        print(f"  signed command OK: {cmd['action']} {pattern} level {cmd.get('level')} ctr {cmd['ctr']} "
              f"(sig {str(cmd.get('sig'))[:8]}..., expires {datetime.fromtimestamp(cmd['exp'], UTC):%H:%M:%S}Z)")
        self.event("cmd_received", cmd_id=cid, pattern=pattern, via="mqtt", src=cmd.get("src"))
        if cmd["action"] == "stop":
            self.state = "idle"
            print("  STOP: horns and siren off")
            self.event("stopped", cmd_id=cid, via="mqtt")
            return
        silent = cmd["action"] == "test" and cmd.get("volume") == 0
        self.state = "testing" if cmd["action"] == "test" else "sounding"
        where = "into the 8 ohm dummy load (silent)" if silent else f"at {cmd.get('volume')} % volume"
        print(f"  {pattern} {where}: {TONE.get(pattern, '')}")
        self.event("started", cmd_id=cid, pattern=pattern, via="mqtt")
        meas = measurements(self.fault, silent)
        faults = ["mic_dead"] if self.fault == "mic_dead" else []
        # Into the dummy load nothing can be heard: a silent test checks the amplifier current only.
        good = is_verified(meas, amp_a_ref=3.3, spl_rise_min_db=15.0, faults=faults + (["mic_dead"] if silent else []))
        shown = f"{meas.get('amp_a', 0):g} A" + (f" +{meas['spl_rise_db']:g} dB" if "spl_rise_db" in meas else
                                                 " into the dummy load" if silent else
                                                 " (microphone dead: current only)")
        if cmd["action"] == "test":
            print(f"  {pattern} test {'passed' if good else 'FAILED'}: {shown}")
            self.event("test_result", cmd_id=cid, kind="silent" if silent else "audible", ok=good, meas=meas,
                       detail="simulated test" + ("" if good else ": amplifier current out of range"))
        elif good:
            print(f"  {pattern} ... verified {shown}")
            self.event("verified", cmd_id=cid, pattern=pattern, meas=meas, via="mqtt", faults=faults or None)
        else:
            print(f"  {pattern} ... NOT verified {shown}")
            self.event("not_verified", cmd_id=cid, pattern=pattern, meas=meas, via="mqtt")
        self.state = "idle"
        self.event("finished", cmd_id=cid)


class Client:
    """One MQTT connection as the thing (awsiotsdk): publish with PUBACK, subscribe with a callback."""

    def __init__(self, endpoint: str, client_id: str, key: str, cert: str, ca: str) -> None:
        try:
            from awscrt import mqtt
            from awsiot import mqtt_connection_builder
        except ImportError:
            raise SystemExit("Install awsiotsdk (`cd backend && uv sync --extra dev`).") from None
        self._mqtt = mqtt
        self._conn = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint, port=8883, cert_filepath=cert, pri_key_filepath=key, ca_filepath=ca,
            client_id=client_id, clean_session=True, keep_alive_secs=30)
        self._conn.connect().result(timeout=20)
        # Messages are handled off the client's event-loop thread: a handler that publishes waits for the
        # PUBACK, which that thread delivers, so handling them on it would block every publish until timeout.
        self._inbox: queue.Queue[tuple[str, bytes, Callable[[dict[str, Any]], None]]] = queue.Queue()
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        while True:
            topic, payload, fn = self._inbox.get()
            try:
                fn(json.loads(payload or b"{}"))
            except Exception as exc:  # a bad message never stops the node
                print(f"  (message on {topic} not handled: {type(exc).__name__}: {exc})", file=sys.stderr)

    def publish(self, topic: str, body: dict[str, Any]) -> None:
        future, _ = self._conn.publish(topic=topic, payload=json.dumps(body, separators=(",", ":")),
                                       qos=self._mqtt.QoS.AT_LEAST_ONCE)
        future.result(timeout=15)

    def subscribe(self, topic: str, fn: Callable[[dict[str, Any]], None]) -> None:
        def on_message(topic: str, payload: bytes, **_: Any) -> None:
            self._inbox.put((topic, payload, fn))

        future, _ = self._conn.subscribe(topic=topic, qos=self._mqtt.QoS.AT_LEAST_ONCE, callback=on_message)
        future.result(timeout=15)

    def close(self) -> None:
        self._conn.disconnect().result(timeout=10)


def credentials(ssm: Any, device: str, into: str) -> tuple[str, str, str, bytes]:
    """Key, certificate, root CA paths and the signing key. Nothing is printed."""
    import os
    import urllib.request

    key_name, cert_name = param_names(device, "siren")
    names = [key_name, cert_name, hmac_param(device, "siren")]
    got = {p["Name"]: p["Value"] for p in ssm.get_parameters(Names=names, WithDecryption=True)["Parameters"]}
    if set(got) != set(names):
        raise SystemExit(f"{device} is not provisioned: run `make device-provision KIND=siren VILLAGE=...` first.")
    key, cert, ca = (os.path.join(into, n) for n in ("device.key", "device.pem", "AmazonRootCA1.pem"))
    _write_private(key, got[key_name])
    _write_private(cert, got[cert_name])
    with urllib.request.urlopen(ROOT_CA_URL, timeout=20) as resp:
        _write_private(ca, resp.read().decode())
    return key, cert, ca, bytes.fromhex(got[names[2]])


def check_sms(device: str, key: bytes, text: str) -> int:
    """Run one SMS through the node's parser and checks (the sender is taken as allow-listed)."""
    v = CommandVerifier(device, {1: key})
    ok, reason = v.accept_sms(text, sender_allowed=True, now=int(time.time()))
    try:
        sms = protocol.parse_sms(text)
        what = f"{sms.action} {sms.level} ctr {sms.ctr}"
    except protocol.ProtocolError:
        what = "unreadable"
    print(f"SMS {what}: " + ("PUKAAR OK" if ok else f"PUKAAR REJECT {reason}"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # a terminal demo, often piped through tee
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("village", nargs="?", default="thunag")
    p.add_argument("--device", help="thing name (default siren-<village>-sim); must end in -sim")
    p.add_argument("--fault", choices=("amp_open", "mic_dead", "battery_low", "tamper"))
    p.add_argument("--offline", type=float, default=0, help="seconds to stay silent before connecting")
    p.add_argument("--heartbeat", type=float, default=300.0, help="seconds between heartbeats")
    p.add_argument("--minutes", type=float, default=0, help="stop after this long (0: until Ctrl-C)")
    p.add_argument("--sms", help="check one signed SMS text offline and exit")
    p.add_argument("--region", default=REGION)
    args = p.parse_args(argv)
    device = args.device or f"siren-{args.village}-sim"
    if not device.endswith("-sim"):
        print(f"{device} is not a labelled simulator (-sim); the simulator will not act as real hardware.",
              file=sys.stderr)
        return 1

    import boto3

    ssm = boto3.client("ssm", region_name=args.region)
    tmp = _secret_dir()
    try:
        key, cert, ca, hkey = credentials(ssm, device, tmp)
        if args.sms:
            return check_sms(device, hkey, args.sms)
        if args.offline:
            print(f"SIMULATED siren {device}: offline for {args.offline:g} s (nothing on any path)")
            time.sleep(args.offline)
        endpoint = ats_endpoint(boto3.client("iot", region_name=args.region))
        client = Client(endpoint, device, key, cert, ca)
        lock = threading.Lock()

        def send(topic: str, body: dict[str, Any]) -> None:
            with lock:
                client.publish(topic, body)

        node = Node(args.village, device, hkey, args.fault, send)
        base = f"$aws/things/{device}/shadow/name/siren"

        def on_doc(doc: dict[str, Any]) -> None:
            state = doc.get("state") or {}
            cmd = (state.get("desired") or state).get("cmd") if isinstance(state, dict) else None
            if isinstance(cmd, dict) and cmd.get("id") and cmd["id"] not in node.verifier.recent_ids:
                with lock:
                    print(f"{clock.iso(datetime.now(UTC))} command {cmd['id']} from the named shadow 'siren'")
                node.command(cmd)
                client.publish(f"{base}/update", {"state": {"reported": {
                    "cmd_id": cmd["id"], "state": node.state, "since": int(time.time()),
                    "last_ctr": node.verifier.last_ctr["mqtt"], "kid": 1, "fw": FW, "clips": "catalog-sim",
                    "faults": [], "soc": node.soc}}})

        client.subscribe(f"{base}/update/delta", on_doc)
        client.subscribe(f"{base}/get/accepted", on_doc)
        print(f"SIMULATED siren {device} on AWS IoT Core ({endpoint}:8883), village {args.village}"
              + (f", fault {args.fault}" if args.fault else "") + "; waiting for signed commands (Ctrl-C to stop)")
        client.publish(f"{base}/get", {})  # on every connect: the shadow, never queued messages
        node.heartbeat()
        if args.fault == "tamper":
            node.event("tamper")
        stop_at = time.monotonic() + args.minutes * 60 if args.minutes else None
        last = time.monotonic()
        try:
            while stop_at is None or time.monotonic() < stop_at:
                time.sleep(1)
                if time.monotonic() - last >= args.heartbeat:
                    node.heartbeat()
                    last = time.monotonic()
        except KeyboardInterrupt:
            pass
        finally:
            client.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
