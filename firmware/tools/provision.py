#!/usr/bin/env python3
"""Write a Pukaar device's identity, keys and settings into its NVS partition.

    # a labelled simulator, TEST ONLY keys from the public test root (bytes 0x00..0x1f):
    python firmware/tools/provision.py --kind siren --device siren-thunag-sim --village thunag --addr 0x0101 \\
        --test-only --sender gauge-janjehli-sim:gauge_status,gauge_alarm,relay_cmd:513 \\
        --sender box-thunag-sim:button,heartbeat,relay_cmd:258 --out build/siren-thunag-sim

    # a real device: its own key and each trusted sender's key come from files (hex, 32 bytes), never
    # from the command line (shell history) and never from this repository
    python firmware/tools/provision.py --kind gauge --device gauge-gohar-01 --village gohar \\
        --key-file /secure/gauge-gohar-01.hex --config gauge-gohar-01.json \\
        --port /dev/ttyACM0 --out /secure/build/gauge-gohar-01

    python firmware/tools/provision.py --self-test   # HKDF, LoRa addresses and the blob layout

What it writes (lib/pukaar_hal/hal_storage.cpp reads the same keys):
  namespace pkr-keys: dev (string), addr (u32), kid (u32), self<kid> (32-byte blob),
                      snd0..snd15 (ProvisionedSender: addr u16, kid u8, roles u8, device char[40],
                      key u8[32], little-endian, 76 bytes), sms_salt (string), sms_to0..3 (string)
  namespace pkr-cfg:  cfg (string, JSON: lib/pukaar_common/pkr_node.h has the shape)

It writes <out>.csv (the esp-idf NVS CSV), then <out>.bin with esp-idf-nvs-partition-gen
(pip install esp-idf-nvs-partition-gen) and, with --port, flashes it with esptool at the NVS partition
of default_8MB.csv (0x9000, 0x5000 bytes). The CSV and the .bin hold keys: keep them off the repo,
and delete them once flashed. The device certificate and key for MQTT are separate: LittleFS
/certs/{ca,device,key}.pem (make device-provision prints them; upload with `pio run -t uploadfs` from a
data/ folder outside git).

Device keys are HKDF-SHA256(root, salt "pukaar-device-root-v1", info "pukaar-dev|<device>|<kid>"), as
backend/src/Pukaar/services/devices/protocol.py derives them. --test-only derives from the public TEST
root and is refused for any id that does not end in "-sim".
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import pathlib
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VECTORS = ROOT / "test" / "vectors" / "protocol_vectors.json"
TEST_ONLY_ROOT = bytes(range(32))  # PUBLIC. The same TEST ONLY root as the golden vectors.
HKDF_SALT = b"pukaar-device-root-v1"
NVS_OFFSET, NVS_SIZE = 0x9000, 0x5000  # default_8MB.csv
ROLES = {"gauge_status": 1, "gauge_alarm": 2, "relay_cmd": 4, "siren_event": 8, "button": 16, "heartbeat": 32,
         "beacon": 64, "ack": 128}
KINDS = ("siren", "gauge", "rain", "box", "relay")
SENDER_FMT = "<HBB40s32s"  # ProvisionedSender in lib/pukaar_hal/pukaar_hal.h


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def derive(root: bytes, device: str, kid: int) -> bytes:
    return hkdf_sha256(root, HKDF_SALT, f"pukaar-dev|{device}|{kid}".encode(), 32)


def lora_addr(device: str) -> int:
    """lib/pukaar_common/pkr_addr.h: SHA-256(id), first two bytes little-endian, never 0 or 0xFFFF."""
    h = hashlib.sha256(device.encode()).digest()
    a = h[0] | (h[1] << 8)
    if a in (0, 0xFFFF):
        a = ((h[2] | (h[3] << 8)) & 0x7FFF) | 1
    return a


def sender_blob(device: str, addr: int, kid: int, roles: int, key: bytes) -> bytes:
    if len(device.encode()) >= 40 or len(key) != 32:
        raise SystemExit(f"sender {device}: id over 39 characters or key not 32 bytes")
    return struct.pack(SENDER_FMT, addr, kid, roles, device.encode(), key)


def read_key(path: str) -> bytes:
    text = pathlib.Path(path).read_text().strip()
    key = bytes.fromhex(text)
    if len(key) != 32:
        raise SystemExit(f"{path}: a key is 32 bytes of hex")
    return key


def parse_sender(spec: str) -> tuple[str, int, int, int]:
    """DEVICE:ROLE,ROLE[:ADDR[:KID]] -> (device, roles, addr, kid)."""
    parts = spec.split(":")
    if len(parts) < 2:
        raise SystemExit(f"--sender {spec}: DEVICE:ROLE,ROLE[:ADDR[:KID]]")
    device, names = parts[0], [r for r in parts[1].split(",") if r]
    bad = [r for r in names if r not in ROLES]
    if bad:
        raise SystemExit(f"--sender {spec}: unknown role(s) {bad}; known: {', '.join(ROLES)}")
    addr = int(parts[2], 0) if len(parts) > 2 and parts[2] else lora_addr(device)
    kid = int(parts[3]) if len(parts) > 3 else 1
    return device, sum(ROLES[r] for r in names), addr, kid


def rows(args: argparse.Namespace) -> list[list[str]]:
    if args.test_only and not args.device.endswith("-sim"):
        raise SystemExit("--test-only keys are for a labelled simulator (an id ending in -sim) only")
    if not args.test_only and not args.key_file:
        raise SystemExit("a real device needs --key-file (its own key, hex); or --test-only for a -sim id")
    key = derive(TEST_ONLY_ROOT, args.device, args.kid) if args.test_only else read_key(args.key_file)
    addr = args.addr if args.addr is not None else lora_addr(args.device)
    out = [["key", "type", "encoding", "value"], ["pkr-keys", "namespace", "", ""],
           ["dev", "data", "string", args.device], ["addr", "data", "u32", str(addr)],
           ["kid", "data", "u32", str(args.kid)], [f"self{args.kid}", "data", "hex2bin", key.hex()]]
    sender_keys = dict(s.split("=", 1) for s in args.sender_key_file)
    for i, spec in enumerate(args.sender):
        if i >= 16:
            raise SystemExit("at most 16 senders")
        device, roles, s_addr, s_kid = parse_sender(spec)
        if args.test_only:
            if not device.endswith("-sim"):
                raise SystemExit(f"--test-only: sender {device} is not a -sim device")
            s_key = derive(TEST_ONLY_ROOT, device, s_kid)
        elif device in sender_keys:
            s_key = read_key(sender_keys[device])
        else:
            raise SystemExit(f"sender {device}: give its key with --sender-key-file {device}=PATH")
        out.append([f"snd{i}", "data", "hex2bin", sender_blob(device, s_addr, s_kid, roles, s_key).hex()])
    if args.sms_salt:
        out.append(["sms_salt", "data", "string", args.sms_salt])
    for i, number in enumerate(args.sms_to[:4]):
        if not number.startswith("+") or not number[1:].isdigit():
            raise SystemExit(f"--sms-to {number}: E.164, like +91XXXXXXXXXX")
        out.append([f"sms_to{i}", "data", "string", number])
    cfg: dict = {}
    if args.config:
        cfg = json.loads(pathlib.Path(args.config).read_text())
    cfg.setdefault("village", args.village)
    if args.kind == "rain":
        cfg["sensor"] = "none"
    text = json.dumps(cfg, separators=(",", ":"))
    if len(text) > 3900:
        raise SystemExit("config JSON over 3900 characters (an NVS string holds 4000)")
    out += [["pkr-cfg", "namespace", "", ""], ["cfg", "data", "string", text]]
    return out


def write_csv(path: pathlib.Path, table: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(table)
    path.chmod(0o600)


def nvs_bin(csv_path: pathlib.Path, bin_path: pathlib.Path) -> bool:
    cmd = [sys.executable, "-m", "esp_idf_nvs_partition_gen", "generate", str(csv_path), str(bin_path), hex(NVS_SIZE)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"no NVS image: pip install esp-idf-nvs-partition-gen ({detail.strip()[:200]})", file=sys.stderr)
        return False
    bin_path.chmod(0o600)
    return True


def flash(bin_path: pathlib.Path, port: str) -> None:
    esptool = shutil.which("esptool.py") or shutil.which("esptool")
    cmd = ([esptool] if esptool else [sys.executable, "-m", "esptool"]) + [
        "--chip", "esp32s3", "--port", port, "write_flash", hex(NVS_OFFSET), str(bin_path)]
    subprocess.run(cmd, check=True)


def self_test() -> int:
    """The derivation and the layouts against the backend's golden vectors (TEST ONLY keys)."""
    v = json.loads(VECTORS.read_text())
    root = bytes.fromhex(v["derivation"]["root_hex"])
    assert root == TEST_ONLY_ROOT, "the vectors' root is the public test root"
    for d in v["derivation"]["devices"]:
        assert derive(root, d["device"], d["kid"]).hex() == d["key_hex"], d["device"]
    assert struct.calcsize(SENDER_FMT) == 76
    assert lora_addr("siren-thunag-sim") == lora_addr("siren-thunag-sim") and 0 < lora_addr("x") < 0xFFFF
    assert parse_sender("box-thunag-sim:button,relay_cmd:258")[1:3] == (16 | 4, 258)
    blob = sender_blob("box-thunag-sim", 258, 1, 20, bytes(32))
    assert blob[:4] == bytes([2, 1, 1, 20]) and blob[4:18] == b"box-thunag-sim"
    args = build_parser().parse_args(["--kind", "siren", "--device", "siren-thunag-sim", "--village", "thunag",
                                      "--test-only", "--sender", "box-thunag-sim:button:258"])
    table = rows(args)
    assert ["dev", "data", "string", "siren-thunag-sim"] in table
    try:
        rows(build_parser().parse_args(["--kind", "siren", "--device", "siren-thunag-01", "--village", "thunag",
                                        "--test-only"]))
        raise AssertionError("test-only keys for a real id")
    except SystemExit:
        pass
    print(f"provision self-test ok ({len(v['derivation']['devices'])} derivations match the golden vectors)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--device", help="the thing name, e.g. siren-thunag-01")
    ap.add_argument("--village")
    ap.add_argument("--kid", type=int, default=1)
    ap.add_argument("--addr", type=lambda s: int(s, 0), help="LoRa address (default: from the id, as the registry)")
    ap.add_argument("--key-file", help="the device's own key, 64 hex characters")
    ap.add_argument("--test-only", action="store_true", help="TEST ONLY keys from the public root; -sim ids only")
    ap.add_argument("--sender", action="append", default=[], help="DEVICE:ROLE,ROLE[:ADDR[:KID]] (repeat)")
    ap.add_argument("--sender-key-file", action="append", default=[], help="DEVICE=PATH (repeat)")
    ap.add_argument("--sms-salt")
    ap.add_argument("--sms-to", action="append", default=[], help="an officer's or the pradhan's number (repeat, 4 at most)")
    ap.add_argument("--config", help="a JSON file for pkr-cfg/cfg (village, endpoint, apn, thresholds, downstream)")
    ap.add_argument("--out", help="output path without extension (<out>.csv, <out>.bin)")
    ap.add_argument("--port", help="flash the NVS image over this serial port with esptool")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if not (args.kind and args.device and args.village and args.out):
        build_parser().error("--kind, --device, --village and --out are required")
    table = rows(args)
    out = pathlib.Path(args.out)
    csv_path, bin_path = out.with_suffix(".csv"), out.with_suffix(".bin")
    write_csv(csv_path, table)
    print(f"wrote {csv_path} (holds keys: delete it once flashed)")
    if nvs_bin(csv_path, bin_path):
        print(f"wrote {bin_path}")
        if args.port:
            flash(bin_path, args.port)
            print(f"flashed {bin_path} to {args.port} at {hex(NVS_OFFSET)}")
    elif args.port:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
