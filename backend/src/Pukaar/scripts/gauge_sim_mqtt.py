"""River-gauge SIMULATOR over MQTT: publishes a rising river to AWS IoT Core with the gauge's own
X.509 certificate, the way a real device would.

This is not hardware and never claims to be. Every reading carries "simulated": true and is
published as the village's registered "-sim" device, so the rules add "gauge_simulated" to the
decision trace and the village page shows a "Simulated" chip. If the registered device is real
hardware (an id that does not end in "-sim"), the simulator refuses to publish.

    python -m Pukaar.scripts.gauge_sim_mqtt gohar           # via `make gauge-sim-mqtt VILLAGE=gohar`
    python -m Pukaar.scripts.gauge_sim_mqtt gohar --slow    # one reading every --interval s

Needs `make gauge-provision VILLAGE=gohar` first: the certificate and private key are read from
SSM (/pukaar/gauge/<device>/cert and /key) into an owner-only temporary directory in memory
(/dev/shm), used for the TLS connection and removed on exit. The Amazon Root CA 1 is downloaded
at run time. Connects with the AWS IoT Device SDK (awsiotsdk) when installed, else paho-mqtt.

Readings go to pukaar/gauge/<village>/<device>/reading; the topic rule hands them to the
gauge-ingest Lambda, which stores them through the same path as the HTTPS route. MQTT gives no
reply, so after each publish the simulator reads the village page until the reading shows up.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from Pukaar.core import clock
from Pukaar.scripts import gauge_sim
from Pukaar.scripts.iot_provision import REGION, ats_endpoint, param_names

ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
CONFIRM_TIMEOUT_S = 30


def topic_for(village: str, device_id: str) -> str:
    return f"pukaar/gauge/{village}/{device_id}/reading"


def payload(at: datetime, cm: float, battery: float) -> dict[str, Any]:
    """What the device publishes. Its identity is the topic (pinned to its certificate by the IoT
    policy); the rule adds village_id and device_id from the topic."""
    return {"at": clock.iso(at), "water_level_cm": cm, "battery_v": battery, "rssi": -71, "simulated": True}


def _secret_dir() -> str:
    base = "/dev/shm" if os.path.isdir("/dev/shm") else None
    return tempfile.mkdtemp(prefix="pukaar-gauge-", dir=base)  # mode 0700


def _write_private(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def fetch_credentials(ssm: Any, device_id: str, into: str) -> tuple[str, str, str]:
    """Write key, certificate and root CA into `into`; return their paths. Nothing is printed."""
    key_name, cert_name = param_names(device_id)
    got = {p["Name"]: p["Value"] for p in
           ssm.get_parameters(Names=[key_name, cert_name], WithDecryption=True)["Parameters"]}
    if set(got) != {key_name, cert_name}:
        raise SystemExit(f"{device_id} is not provisioned ({key_name} missing): run `make gauge-provision` first.")
    key, cert, ca = (os.path.join(into, n) for n in ("device.key", "device.pem", "AmazonRootCA1.pem"))
    _write_private(key, got[key_name])
    _write_private(cert, got[cert_name])
    with urllib.request.urlopen(ROOT_CA_URL, timeout=20) as resp:
        pem = resp.read().decode()
    if "BEGIN CERTIFICATE" not in pem:
        raise SystemExit(f"unexpected content at {ROOT_CA_URL}")
    _write_private(ca, pem)
    return key, cert, ca


class Publisher:
    """One MQTT connection as the device: awsiotsdk (awscrt) if importable, else paho-mqtt."""

    def __init__(self, endpoint: str, client_id: str, key: str, cert: str, ca: str) -> None:
        try:
            from awscrt import mqtt
            from awsiot import mqtt_connection_builder
        except ImportError:
            mqtt = None
        if mqtt is not None:
            self.lib = "awsiotsdk"
            self._qos = mqtt.QoS.AT_LEAST_ONCE
            self._conn = mqtt_connection_builder.mtls_from_path(
                endpoint=endpoint, port=8883, cert_filepath=cert, pri_key_filepath=key, ca_filepath=ca,
                client_id=client_id, clean_session=True, keep_alive_secs=30)
            self._conn.connect().result(timeout=20)
            return
        try:
            import paho.mqtt.client as paho
        except ImportError:
            raise SystemExit("Install awsiotsdk (`cd backend && uv sync --extra dev`) or paho-mqtt.") from None
        self.lib = "paho-mqtt"
        try:
            self._paho = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:  # paho-mqtt 1.x
            self._paho = paho.Client(client_id=client_id)
        self._paho.tls_set(ca_certs=ca, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self._paho.connect(endpoint, 8883, keepalive=30)
        self._paho.loop_start()

    def publish(self, topic: str, body: dict[str, Any]) -> None:
        data = json.dumps(body, separators=(",", ":"))
        if self.lib == "awsiotsdk":
            future, _ = self._conn.publish(topic=topic, payload=data, qos=self._qos)
            future.result(timeout=15)  # PUBACK from the broker
        else:
            info = self._paho.publish(topic, data, qos=1)
            info.wait_for_publish(timeout=15)
            if not info.is_published():
                raise SystemExit("no PUBACK within 15 s: is the certificate attached to the thing and the policy?")

    def close(self) -> None:
        if self.lib == "awsiotsdk":
            self._conn.disconnect().result(timeout=10)
        else:
            self._paho.loop_stop()
            self._paho.disconnect()


def confirm(base: str, village: str, at: str) -> dict[str, Any] | None:
    """Poll the public village page until the reading stamped `at` is the gauge's latest."""
    deadline = time.monotonic() + CONFIRM_TIMEOUT_S
    while time.monotonic() < deadline:
        status, detail = gauge_sim._request(f"{base.rstrip('/')}/villages/{village}")
        g = (detail.get("gauge") or {}) if status == 200 else {}
        latest = g.get("latest") or {}
        if latest.get("at") and clock.parse(latest["at"]) >= clock.parse(at):
            return {"gauge": g.get("level"), "village": (detail.get("village") or {}).get("level"),
                    "transport": latest.get("transport", "-")}
        time.sleep(1.5)
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("village", nargs="?", default="gohar")
    p.add_argument("--base", help="API base URL (default: the pukaar-dev stack's ApiUrl), used to read the village")
    p.add_argument("--slow", action="store_true", help="real time: one reading every --interval s")
    p.add_argument("--interval", type=float, default=70.0, help="seconds between readings with --slow")
    p.add_argument("--steps", type=int, default=12, help="readings with --slow (default mode sends five)")
    p.add_argument("--to", choices=("watch", "warning", "critical"), default="warning", help="band to rise past")
    p.add_argument("--region", default=REGION)
    args = p.parse_args(argv)

    import boto3

    base = args.base or gauge_sim.stack_api_url()
    status, detail = gauge_sim._request(f"{base.rstrip('/')}/villages/{args.village}")
    cfg = (detail.get("gauge") or {}).get("config") if status == 200 else None
    if not cfg:
        print(f"GET /villages/{args.village} -> {status}: no gauge configured (re-run `make seed`?)", file=sys.stderr)
        return 1
    device_id = cfg["device_id"]
    if not device_id.endswith("-sim"):
        print(f"{args.village}'s gauge {device_id} is real hardware; the simulator will not publish as it.",
              file=sys.stderr)
        return 1

    endpoint = ats_endpoint(boto3.client("iot", region_name=args.region))
    topic = topic_for(args.village, device_id)
    steps = args.steps if args.slow else 5
    stages = gauge_sim.profile(cfg, steps, args.to)
    tmp = _secret_dir()
    try:
        key, cert, ca = fetch_credentials(boto3.client("ssm", region_name=args.region), device_id, tmp)
        pub = Publisher(endpoint, device_id, key, cert, ca)
        print(f"SIMULATED gauge {device_id} over MQTT ({pub.lib}, X.509) -> {endpoint}:8883 topic {topic}")
        print(f"  thresholds cm: watch {cfg['watch_cm']:g}, warning {cfg['warning_cm']:g}, "
              f"critical {cfg['critical_cm']:g}")
        # Default: five readings 61 s apart in time (the server keeps one per device per minute),
        # the oldest under five minutes ago, each confirmed before the next is sent.
        start = datetime.now(UTC) - timedelta(seconds=gauge_sim.FAST_OLDEST_S)
        try:
            for i, cm in enumerate(stages):
                at = datetime.now(UTC) if args.slow else start + timedelta(seconds=gauge_sim.FAST_STEP_S * i)
                body = payload(at, cm, round(4.05 - 0.01 * i, 2))
                pub.publish(topic, body)
                seen = confirm(base, args.village, body["at"])
                shown = (f"gauge={seen['gauge'] or '-'} village={seen['village']} via {seen['transport']}"
                         if seen else f"not on the village page after {CONFIRM_TIMEOUT_S} s (check the "
                                      "gauge-ingest Lambda logs and the worker DLQ)")
                print(f"  {body['at']}  {cm:7.1f} cm  -> published (PUBACK)  {shown}")
                if args.slow and i < len(stages) - 1:
                    time.sleep(args.interval)
        finally:
            pub.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
