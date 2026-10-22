"""River-gauge SIMULATOR: signs and POSTs a rising river to /sensors/{village}/readings.

This is not hardware and never claims to be. Every reading it sends carries
"simulated": true and the village's registered "-sim" device id, so the rules
add "gauge_simulated" to the decision trace and the village page shows a
"Simulated" chip. If the village's registered device is real hardware (an id
that does not end in "-sim"), the simulator refuses to send.

    python -m Pukaar.scripts.gauge_sim gohar                       # deployed stack, one reading per 70 s
    python -m Pukaar.scripts.gauge_sim gohar --fast                # three hours of backfill, then five live readings
    python -m Pukaar.scripts.gauge_sim gohar --base http://127.0.0.1:8000 --fast
    python -m Pukaar.scripts.gauge_sim --print-key gauge-gohar-01  # provisioning key for a real device

Timestamps are what the server counts: it accepts one live reading per device
per minute and only timestamps from the last five minutes. --fast therefore
first posts three hours of the river's slow rise as backfill (as a gauge does
after a link outage: stored and drawn, never alerted on), then five live
readings 61 s apart inside the window (oldest about 4 m 50 s ago), each just
past the target band. The server counts a band only when 2 of the last 3 good
readings reach it, so the second live reading confirms it. Real-time mode
sends one reading every --interval s along a smooth rise; a rise that fast also
trips the rate-of-rise rule (one band up, "rising fast"), as a real river would.

Every reading is payload v2 (seq, boot, samples, spread, quality, error bits,
temperature, battery and solar millivolts, firmware), still labelled simulated.

The signing key comes from the link secret: SSM on the deployed stack (run via
`make gauge-sim`, which loads the stack environment), or PUKAAR_LINK_SECRET for
a local server started with the same value.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from Pukaar.core import clock
from Pukaar.services import gauge

FAST_STEP_S = 61
FAST_OLDEST_S = 290
BACKFILL_HOURS = 3
BACKFILL_STEP_MIN = 5
FW = "sim-2.0"


def stack_api_url(stack: str | None = None, region: str | None = None) -> str:
    if os.environ.get("STACK_ApiUrl"):
        return os.environ["STACK_ApiUrl"]
    stack = stack or os.environ.get("PUKAAR_STACK", "pukaar-dev")
    region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    out = subprocess.run(
        ["aws", "cloudformation", "describe-stacks", "--stack-name", stack, "--region", region,
         "--query", "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue", "--output", "text"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def profile(cfg: dict, steps: int, to: str) -> list[float]:
    """Stage values (cm) rising from well below watch to just past the target band."""
    watch, top = float(cfg["watch_cm"]), float(cfg[f"{to}_cm"])
    start, end = 0.55 * watch, top * 1.06
    out = []
    for i in range(steps):
        x = i / max(1, steps - 1)
        out.append(round(start + (end - start) * x * x * (3 - 2 * x), 1))  # smoothstep: slow, fast, slow
    return out


def fast_plan(cfg: dict, to: str, now: datetime) -> tuple[list[tuple[datetime, float]], list[tuple[datetime, float]]]:
    """(backfill, live): a slow rise over BACKFILL_HOURS ending just under the target band, then
    five live readings 61 s apart, each a little past it (too slow to count as rising fast)."""
    top = float(cfg[f"{to}_cm"])
    start = 0.55 * float(cfg["watch_cm"])
    oldest_live = now - timedelta(seconds=FAST_OLDEST_S)
    n = BACKFILL_HOURS * 60 // BACKFILL_STEP_MIN
    back = []
    for i in range(n):
        x = i / max(1, n - 1)
        at = oldest_live - timedelta(minutes=BACKFILL_STEP_MIN * (n - i))
        back.append((at, round(start + (top - 10 - start) * x, 1)))
    live = [(oldest_live + timedelta(seconds=FAST_STEP_S * i), round(top + 2 + 2.5 * i, 1)) for i in range(5)]
    return back, live


def reading_body(at: datetime, cm: float, battery: float) -> dict:
    """One simulated payload-v2 reading (no device id: the HTTPS body adds it, MQTT uses the topic)."""
    return {"at": clock.iso(at), "water_level_cm": cm, "battery_v": battery, "rssi": -71, "simulated": True,
            "v": 2, "seq": int(at.timestamp()) // 60, "boot": 0, "samples_ok": 9, "samples_n": 9, "iqr_mm": 6,
            "quality": 95, "err": 0, "temp_c": 18.5, "battery_mv": round(battery * 1000), "solar_mv": 5200,
            "fw": FW}


def _request(url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"raw": body.decode(errors="replace")[:300]}


def send(base: str, village: str, device_id: str, key: str, at: datetime, cm: float, battery: float) -> tuple[int, dict]:
    body = json.dumps({"device_id": device_id, **reading_body(at, cm, battery)}, separators=(",", ":")).encode()
    headers = {"content-type": "application/json", gauge.SIGNATURE_HEADER: gauge.sign(key, body)}
    return _request(f"{base.rstrip('/')}/sensors/{village}/readings", body, headers)


def send_backfill(base: str, village: str, device_id: str, key: str,
                  points: list[tuple[datetime, float]]) -> tuple[int, dict]:
    readings = [{**reading_body(at, cm, 4.05), "buffered": True} for at, cm in points]
    body = json.dumps({"device_id": device_id, "readings": readings}, separators=(",", ":")).encode()
    headers = {"content-type": "application/json", gauge.SIGNATURE_HEADER: gauge.sign(key, body)}
    return _request(f"{base.rstrip('/')}/sensors/{village}/backfill", body, headers)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("village", nargs="?", default="gohar")
    p.add_argument("--base", help="API base URL (default: the pukaar-dev stack's ApiUrl)")
    p.add_argument("--fast", action="store_true", help="backfill a slow rise, then five live readings 61 s apart")
    p.add_argument("--interval", type=float, default=70.0, help="seconds between readings in real-time mode")
    p.add_argument("--steps", type=int, default=12, help="readings in real-time mode")
    p.add_argument("--to", choices=("watch", "warning", "critical"), default="warning", help="band to rise past")
    p.add_argument("--print-key", metavar="DEVICE_ID", help="print the signing key for a device and exit")
    args = p.parse_args(argv)

    from Pukaar.core.secrets import get_secret

    secret = get_secret("link_secret")
    if not secret:
        print("No link secret: run via `make gauge-sim` (stack env) or set PUKAAR_LINK_SECRET.", file=sys.stderr)
        return 2
    if args.print_key:
        print(gauge.device_key(secret, args.print_key))
        return 0

    base = args.base or stack_api_url()
    status, detail = _request(f"{base.rstrip('/')}/villages/{args.village}")
    if status != 200:
        print(f"GET /villages/{args.village} -> {status} {detail}", file=sys.stderr)
        return 1
    cfg = detail.get("gauge", {}) and detail["gauge"].get("config")
    if not cfg:
        print(f"{args.village} has no gauge configured (re-run `make seed`?)", file=sys.stderr)
        return 1
    device_id = cfg["device_id"]
    if not device_id.endswith("-sim"):
        print(f"{args.village}'s gauge {device_id} is real hardware; the simulator will not send as it.", file=sys.stderr)
        return 1
    key = gauge.device_key(secret, device_id)

    print(f"SIMULATED gauge {device_id} -> {base} ({args.village}); thresholds cm: watch {cfg['watch_cm']:g}, "
          f"warning {cfg['warning_cm']:g}, critical {cfg['critical_cm']:g}")
    if args.fast:
        back, live = fast_plan(cfg, args.to, datetime.now(UTC))
        status, out = send_backfill(base, args.village, device_id, key, back)
        print(f"  backfill {len(back)} readings {clock.iso(back[0][0])} .. {clock.iso(back[-1][0])} -> {status} "
              f"stored={out.get('stored', '-')} duplicate={out.get('duplicate', '-')} (never alerts)")
        if status >= 400:
            print(f"  {out}", file=sys.stderr)
            return 1
    else:
        live = [(datetime.now(UTC), cm) for cm in profile(cfg, args.steps, args.to)]
    for i, (planned, cm) in enumerate(live):
        at = planned if args.fast else datetime.now(UTC)
        battery = round(4.05 - 0.01 * i, 2)
        status, out = send(base, args.village, device_id, key, at, cm, battery)
        print(f"  {clock.iso(at)}  {cm:7.1f} cm  -> {status} {out.get('status', '')} gauge={out.get('gauge_level', '-')} "
              f"counted={out.get('effective_level', '-')}{' rising fast' if out.get('rising_fast') else ''} "
              f"quality={out.get('quality', '-')} "
              f"village={out.get('village_level', '-')}{'  alert ' + out['alert_id'] if out.get('alert_id') else ''}"
              + ("" if status == 202 else f"  {out}"))
        if status >= 400:
            return 1
        if not args.fast and i < len(live) - 1:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
