"""Golden test vectors for the device protocol, shared with the firmware's native tests.

    python -m Pukaar.scripts.protocol_vectors           # write firmware/test/vectors/protocol_vectors.json
    python -m Pukaar.scripts.protocol_vectors --check   # exit 1 if the checked-in file is stale

Everything comes from services/devices/protocol.py and siren_model.py with FIXED, PUBLIC keys: the
root below is bytes 0x00..0x1f and is TEST ONLY. It must never be used on a device or a stack. The
output is deterministic (no clock, no randomness), so the file only changes when the protocol does.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from Pukaar.services.devices import protocol as p
from Pukaar.services.devices.siren_model import (
    FRAME_SKEW_S,
    PATTERN_DEFAULTS,
    RECENT_IDS,
    SEND_CTR_BOOT_SKIP,
    UNSYNCED_EXP_WINDOW_S,
    CommandVerifier,
    FrameVerifier,
    Sender,
    is_verified,
)

OUT = Path(__file__).resolve().parents[4] / "firmware" / "test" / "vectors" / "protocol_vectors.json"
TEST_ROOT = bytes(range(32))  # TEST ONLY
NOW = 1761121805  # 2025-10-22T08:30:05Z: a fixed "now" for the checks
SIREN, BOX, GAUGE, RELAY = "siren-thunag-01", "box-thunag-01", "gauge-janjehli-01", "relay-seraj-01"
ADDR = {SIREN: 0x0101, BOX: 0x0102, GAUGE: 0x0201, RELAY: 0x0301}


def key(device: str, kid: int = 1) -> bytes:
    return p.derive_device_key(TEST_ROOT, device, kid)


def _cmd(**over: Any) -> dict[str, Any]:
    base = {"id": "cmd_01jb6x7k8m9n0p1q2r3s4t5v6w", "action": "sound", "pattern": "W1",
            "clip": "thunag.warning.hi.v3", "clip_sha256_16": "9f1c2a7be03d4c55", "level": "warning",
            "alert_id": "alr_01jb5zz0a1b2c3d4e5f6g7h8j9", **PATTERN_DEFAULTS["W1"],
            "iat": 1761121800, "exp": 1761123600, "ctr": 412, "src": "approval", "kid": 1}
    base.update(over)
    return base


def _signed(cmd: dict[str, Any], device: str = SIREN) -> dict[str, Any]:
    out = dict(cmd)
    out["sig"] = p.sign_command(key(device, cmd["kid"]), cmd, device)
    return out


def commands() -> list[dict[str, Any]]:
    cases = [
        ("warning_w1", _cmd()),
        ("critical_c1", _cmd(id="cmd_01jb6x7k8m9n0p1q2r3s4t5v6x", pattern="C1", level="critical",
                             clip="thunag.critical.hi.v3", clip_sha256_16="0a1b2c3d4e5f6071", ctr=413,
                             **PATTERN_DEFAULTS["C1"])),
        ("stop", _cmd(id="cmd_01jb6x7k8m9n0p1q2r3s4t5v6y", action="stop", pattern=None, clip=None,
                      clip_sha256_16=None, level=None, cycles=0, repeat_every_s=0, repeat_cycles=0, cap_on_s=0,
                      volume=0, ctr=414, src="officer_manual")),
        ("test_t1_kid2", _cmd(id="cmd_01jb6x7k8m9n0p1q2r3s4t5v6z", action="test", pattern="T1", level="test",
                              clip="test.hi.v3", clip_sha256_16="1122334455667788", alert_id=None, ctr=415,
                              src="officer_manual", kid=2, **PATTERN_DEFAULTS["T1"])),
        ("all_clear_a1", _cmd(id="cmd_01jb6x7k8m9n0p1q2r3s4t5v70", pattern="A1", level="all_clear",
                              clip="thunag.allclear.hi.v3", clip_sha256_16="8899aabbccddeeff", ctr=416,
                              src="all_clear", **PATTERN_DEFAULTS["A1"])),
    ]
    out = []
    for name, cmd in cases:
        signed = _signed(cmd)
        out.append({"name": name, "device": SIREN, "kid": cmd["kid"], "key_hex": key(SIREN, cmd["kid"]).hex(),
                    "cmd": signed, "canonical": p.canonical_command(cmd, SIREN), "sig": signed["sig"]})
    return out


def command_checks() -> list[dict[str, Any]]:
    """Ordered sequences for the acceptance matrix: each step's result depends on the steps before."""
    keys = {1: key(SIREN, 1), 2: key(SIREN, 2)}
    w1 = _signed(_cmd())
    c1 = _signed(_cmd(id="cmd_c1", pattern="C1", level="critical", ctr=420, **PATTERN_DEFAULTS["C1"]))
    forged = dict(c1, pattern="W1")  # the C1's signature on different fields
    old = _signed(_cmd(id="cmd_old", ctr=411))
    wrong_kid = dict(_signed(_cmd(id="cmd_k3", ctr=430)), kid=3)
    late = _signed(_cmd(id="cmd_late", ctr=431, exp=NOW - 1))
    same_on_lora = _signed(_cmd(id="cmd_lora", ctr=412))
    far = _signed(_cmd(id="cmd_far", ctr=440, exp=NOW + UNSYNCED_EXP_WINDOW_S + 60))
    near = _signed(_cmd(id="cmd_near", ctr=441, exp=NOW + 600))
    steps = [("w1 first time", w1, "mqtt", NOW), ("the same command again", w1, "mqtt", NOW),
             ("an older counter", old, "mqtt", NOW), ("signature from other fields", forged, "mqtt", NOW),
             ("c1 newer counter", c1, "mqtt", NOW), ("unknown kid", wrong_kid, "mqtt", NOW),
             ("arrives after exp", late, "mqtt", NOW), ("lora path keeps its own counter", same_on_lora, "lora", NOW),
             ("clock unsynced, exp beyond 12 h of the last known time", far, "mqtt", None),
             ("clock unsynced, exp within 12 h", near, "mqtt", None)]
    v = CommandVerifier(SIREN, keys)
    seq = []
    for label, cmd, via, now in steps:
        ok, reason = v.accept(cmd, via, now)
        seq.append({"label": label, "via": via, "now": now, "cmd": cmd, "accept": ok, "reason": reason})
    boot = CommandVerifier.after_boot(SIREN, keys, {"last_ctr": {"mqtt": 441, "sms": 0, "lora": 412},
                                                    "recent_ids": [], "last_known_time": NOW})
    boot_steps = []
    for label, ctr in (("after boot, the stored counter again", 441), ("after boot, the next counter", 442)):
        cmd = _signed(_cmd(id=f"cmd_boot_{ctr}", ctr=ctr))
        ok, reason = boot.accept(cmd, "mqtt", NOW)
        boot_steps.append({"label": label, "via": "mqtt", "now": NOW, "cmd": cmd, "accept": ok, "reason": reason})
    return [{"name": "acceptance_matrix", "device": SIREN, "keys_by_kid": {"1": keys[1].hex(), "2": keys[2].hex()},
             "initial_state": {"last_ctr": {"mqtt": 0, "sms": 0, "lora": 0}, "recent_ids": [], "last_known_time": 0},
             "steps": seq},
            {"name": "boot_restore", "device": SIREN, "keys_by_kid": {"1": keys[1].hex()},
             "stored_state": {"last_ctr": {"mqtt": 441, "sms": 0, "lora": 412}, "recent_ids": [],
                              "last_known_time": NOW},
             "receive_ctr_boot_bump": 0, "steps": boot_steps}]


def _hexed(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in fields.items()}


def _frame(name: str, device: str, ftype: p.FrameType, fields: dict[str, Any], *, dst: int, ctr: int,
           ts: int = NOW, payload: bytes | None = None) -> dict[str, Any]:
    body = payload if payload is not None else p.pack_payload(ftype, fields)
    data = p.encode_frame(key(device), ftype=ftype, src=ADDR[device], dst=dst, ctr=ctr, ts=ts, payload=body)
    return {"name": name, "src_device": device, "key_hex": key(device).hex(),
            "header": {"ver": p.FRAME_VERSION, "type": int(ftype), "src": ADDR[device], "dst": dst, "ctr": ctr,
                       "ts": ts, "len": len(body)},
            "payload_fields": _hexed(fields), "payload_hex": body.hex(), "mac_hex": data[-p.FRAME_MAC_BYTES:].hex(),
            "frame_hex": data.hex()}


def frames() -> list[dict[str, Any]]:
    w1 = _signed(_cmd())
    compact = p.compact_command(key(SIREN), w1, SIREN)
    compact_fields = p.unpack_payload(p.FrameType.SIREN_CMD_WRAPPED, compact)
    gauge = {"level": 3, "stage_cm": 312, "rise_10min_cm": 41, "quality": 95, "cloud_ok": 0, "rain_15min_tenths_mm": 87}
    out = [
        _frame("gauge_alarm", GAUGE, p.FrameType.GAUGE_ALARM, gauge, dst=ADDR[SIREN], ctr=5001),
        _frame("gauge_status_unsynced_clock", GAUGE, p.FrameType.GAUGE_STATUS,
               {**gauge, "level": 1, "stage_cm": 140, "rise_10min_cm": -3}, dst=p.BROADCAST, ctr=5002, ts=0),
        _frame("box_button_key_critical", BOX, p.FrameType.BUTTON, {"button": 3, "key_pos": 2, "hold_ms": 3200},
               dst=ADDR[SIREN], ctr=77),
        _frame("box_heartbeat", BOX, p.FrameType.HEARTBEAT,
               {"state": 0, "soc": 86, "batt_dv": 132, "faults": 0, "outbox": 2}, dst=p.BROADCAST, ctr=78),
        _frame("siren_event_verified", SIREN, p.FrameType.SIREN_EVENT,
               {"type": p.EVENT_CODES["verified"], "cmd_id48": p.cmd_id48(w1["id"]), "verified": 1, "amp_a_x10": 31,
                "spl_rise_db": 24}, dst=ADDR[BOX], ctr=9001),
        _frame("relay_beacon", RELAY, p.FrameType.RELAY_BEACON,
               {"bus_dv": 131, "bus_ma": 42, "soc": 77, "noise_dbm": -118}, dst=p.BROADCAST, ctr=12),
        _frame("ack", SIREN, p.FrameType.ACK, {"acked_src": ADDR[BOX], "acked_ctr": 77}, dst=ADDR[BOX], ctr=9002),
        {**_frame("siren_cmd_wrapped_by_box", BOX, p.FrameType.SIREN_CMD_WRAPPED, compact_fields, dst=ADDR[SIREN],
                  ctr=79, payload=compact),
         "inner": {"device": SIREN, "siren_key_hex": key(SIREN).hex(),
                   "signed_bytes_hex": (b"PKR1C|" + SIREN.encode() + b"|" + compact[:20]).hex(),
                   "fields": p.open_compact_command(key(SIREN), compact, SIREN), "from_cmd": w1}},
    ]
    return out


def frame_rejects(good: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each case: the frame bytes and why a receiver configured as `senders` refuses it."""
    alarm = bytes.fromhex(good[0]["frame_hex"])
    wrapped = next(f for f in good if f["name"] == "siren_cmd_wrapped_by_box")
    inner = bytearray(bytes.fromhex(wrapped["payload_hex"]))
    inner[10] ^= 0x01  # the relay changes cap_on_s inside the command and re-MACs the frame with its own key
    forged_inner = p.encode_frame(key(RELAY), ftype=p.FrameType.SIREN_CMD_WRAPPED, src=ADDR[RELAY], dst=ADDR[SIREN],
                                  ctr=13, ts=NOW, payload=bytes(inner))
    tampered = bytearray(alarm)
    tampered[16] ^= 0x01
    bad_ver = bytearray(alarm)
    bad_ver[0] = 2
    box_as_gauge = p.encode_frame(key(BOX), ftype=p.FrameType.GAUGE_ALARM, src=ADDR[BOX], dst=ADDR[SIREN], ctr=80,
                                  ts=NOW, payload=bytes.fromhex(good[0]["payload_hex"]))
    skewed = p.encode_frame(key(GAUGE), ftype=p.FrameType.GAUGE_ALARM, src=ADDR[GAUGE], dst=ADDR[SIREN], ctr=5003,
                            ts=NOW - FRAME_SKEW_S, payload=bytes.fromhex(good[0]["payload_hex"]))
    unknown = p.encode_frame(key("gauge-unknown-01"), ftype=p.FrameType.GAUGE_ALARM, src=0x0999, dst=ADDR[SIREN],
                             ctr=1, ts=NOW, payload=bytes.fromhex(good[0]["payload_hex"]))
    cases = [("truncated", alarm[:-1]), ("version", bytes(bad_ver)), ("tampered_payload", bytes(tampered)),
             ("oversize", alarm + bytes(65 - len(alarm))), ("unknown_src", unknown), ("role", box_as_gauge),
             ("replayed", alarm), ("clock_skew", skewed)]
    senders = {ADDR[GAUGE]: Sender(GAUGE, key(GAUGE), ("gauge_status", "gauge_alarm")),
               ADDR[BOX]: Sender(BOX, key(BOX), ("button", "heartbeat", "relay_cmd")),
               ADDR[RELAY]: Sender(RELAY, key(RELAY), ("beacon", "relay_cmd"))}
    v = FrameVerifier(senders)
    first = v.accept(alarm, NOW)  # the genuine alarm once, so the same bytes again are a replay
    assert first[0], first
    out = []
    for name, data in cases:
        ok, reason, _ = v.accept(data, NOW)
        assert not ok, name
        out.append({"name": name, "frame_hex": data.hex(), "now": NOW, "expect_reason": reason})
    ok, reason, frame = v.accept(forged_inner, NOW)
    opened = p.open_compact_command(key(SIREN), frame.payload, SIREN) if frame else None
    assert ok and opened is None  # the outer MAC is the relay's own and valid; the inner command is not
    out.append({"name": "forwarder_forges_inner_command", "frame_hex": forged_inner.hex(), "now": NOW,
                "expect_reason": "ok_outer_bad_inner", "outer_accepted": ok, "inner_valid": False})
    # A reboot: the per-sender counters come back exactly (written through on accept), so the
    # gauge's next GAUGE_ALARM is accepted at once; anything at or below the stored counter is not.
    stored = v.persisted()
    rebooted = FrameVerifier.after_boot(senders, stored)
    nxt = p.encode_frame(key(GAUGE), ftype=p.FrameType.GAUGE_ALARM, src=ADDR[GAUGE], dst=ADDR[SIREN],
                         ctr=stored[ADDR[GAUGE]] + 1, ts=NOW, payload=bytes.fromhex(good[0]["payload_hex"]))
    reboot_cases = []
    for name, data in (("replay_of_the_last_frame", alarm), ("next_frame", nxt), ("next_frame_again", nxt)):
        ok, reason, _ = rebooted.accept(data, NOW)
        reboot_cases.append({"name": name, "frame_hex": data.hex(), "now": NOW, "expect_reason": reason})
    assert [c["expect_reason"] for c in reboot_cases] == ["replayed", "ok", "replayed"], reboot_cases
    return [{"receiver": SIREN, "senders": {f"0x{a:04x}": {"device": s.device_id, "key_hex": s.key.hex(),
                                                             "roles": list(s.roles)} for a, s in senders.items()},
             "accepted_first": {"name": "gauge_alarm", "frame_hex": alarm.hex()}, "cases": out,
             "after_reboot": {"stored_last_ctr": {f"0x{a:04x}": c for a, c in stored.items()},
                              "cases": reboot_cases}}]


def sms() -> dict[str, Any]:
    exp = NOW + 1800
    good = []
    for name, action, level, ctr in (("sound_critical", "sound", "critical", 413), ("stop", "stop", "warning", 414),
                                     ("test", "test", "test", 415)):
        text = p.sms_text(key(SIREN), SIREN, action, level, ctr, exp)
        a, lv = p.SMS_ACTIONS[action], p.SMS_LEVELS[level]
        good.append({"name": name, "device": SIREN, "key_hex": key(SIREN).hex(), "action": action, "level": level,
                     "ctr": ctr, "exp": exp, "signing_string": p.sms_signing_string(SIREN, a, lv, ctr, exp),
                     "text": text, "length": len(text)})
    base = good[0]["text"]
    lower = base.replace("PKR1", "pkr1", 1)
    parts = base.split(" ")
    wrong_device = " ".join([parts[0], "siren-thunag-02", *parts[2:]])
    bad_sig = base[:-1] + ("0" if base[-1] != "0" else "1")
    checks = [("case_insensitive_prefix", lower, True, NOW), ("unicode", base + " ख़", False, NOW),
              ("over_160", base + " " + "X" * 160, False, NOW), ("wrong_device", wrong_device, False, NOW),
              ("bad_sig", bad_sig, False, NOW), ("replayed", base, False, NOW), ("expired", good[2]["text"], False, exp + 1),
              ("sender_not_allowed", good[1]["text"], False, NOW)]
    v = CommandVerifier(SIREN, {1: key(SIREN)})
    first = v.accept_sms(base, sender_allowed=True, now=NOW)
    assert first == (True, "ok"), first
    out = []
    for name, text, _, now in checks:
        if name == "case_insensitive_prefix":
            fresh = CommandVerifier(SIREN, {1: key(SIREN)})
            ok, reason = fresh.accept_sms(text, sender_allowed=True, now=now)
        else:
            ok, reason = v.accept_sms(text, sender_allowed=name != "sender_not_allowed", now=now)
        out.append({"name": name, "text": text, "now": now, "sender_allowed": name != "sender_not_allowed",
                    "accept": ok, "reason": reason})
    return {"good": good, "checks": {"first_accepted": base, "cases": out},
            "sender_hash": {"salt": "TEST-ONLY-SALT", "e164": "+919800000001",
                            "sha256_hex": p.sender_hash("TEST-ONLY-SALT", "+919800000001")}}


def verification() -> list[dict[str, Any]]:
    cases = [("ok", {"amp_a": 3.1, "spl_rise_db": 24.5}, []), ("amp_low", {"amp_a": 1.9, "spl_rise_db": 24.5}, []),
             ("amp_high", {"amp_a": 5.0, "spl_rise_db": 24.5}, []), ("quiet", {"amp_a": 3.1, "spl_rise_db": 9.0}, []),
             ("mic_dead_current_ok", {"amp_a": 3.1}, ["mic_dead"]), ("mic_dead_no_current", {"amp_a": 0.2}, ["mic_dead"]),
             ("no_measurement", {}, [])]
    return [{"name": n, "meas": m, "faults": f, "amp_a_ref": 3.3, "spl_rise_min_db": 15.0,
             "verified": is_verified(m, amp_a_ref=3.3, spl_rise_min_db=15.0, faults=f)} for n, m, f in cases]


def build() -> dict[str, Any]:
    good_frames = frames()
    return {
        "_warning": "TEST ONLY. Every key in this file is derived from a public root (bytes 0x00..0x1f). "
                    "Never flash these keys or use this root on a device or a stack.",
        "version": 1,
        "generator": "backend/src/Pukaar/scripts/protocol_vectors.py (python -m Pukaar.scripts.protocol_vectors)",
        "source": "backend/src/Pukaar/services/devices/protocol.py, siren_model.py",
        "constants": {"proto": p.PROTO, "cmd_sig_bytes": p.CMD_SIG_BYTES, "frame_mac_bytes": p.FRAME_MAC_BYTES,
                      "inner_sig_bytes": p.INNER_SIG_BYTES, "sms_sig_bytes": p.SMS_SIG_BYTES,
                      "frame_max": p.FRAME_MAX, "payload_max": p.PAYLOAD_MAX, "frame_version": p.FRAME_VERSION,
                      "broadcast": p.BROADCAST, "recent_ids": RECENT_IDS, "receive_ctr_boot_bump": 0,
                      "send_ctr_boot_skip": SEND_CTR_BOOT_SKIP,
                      "unsynced_exp_window_s": UNSYNCED_EXP_WINDOW_S, "frame_skew_s": FRAME_SKEW_S,
                      "sms_max": p.SMS_MAX, "crockford_alphabet": p.CROCKFORD, "hkdf_salt": p.HKDF_SALT.decode(),
                      "hkdf_info": "pukaar-dev|<device>|<kid>", "now": NOW},
        "enums": {"frame_types": {t.name: int(t) for t in p.FrameType}, "level": p.LEVEL_CODES,
                  "action": p.ACTION_CODES, "pattern": p.PATTERN_CODES, "cmd_level": p.CMD_LEVEL_CODES,
                  "button": p.BUTTON_CODES, "key_pos": p.KEY_POS_CODES, "state": p.STATE_CODES,
                  "event": p.EVENT_CODES, "sms_action": p.SMS_ACTIONS, "sms_level": p.SMS_LEVELS,
                  "payload_layouts": {p.FrameType(t).name: {"struct": fmt, "fields": list(names)}
                                      for t, (fmt, names) in p.PAYLOADS.items()},
                  "pattern_defaults": PATTERN_DEFAULTS},
        "derivation": {"root_hex": TEST_ROOT.hex(),
                       "devices": [{"device": d, "kid": k, "key_hex": key(d, k).hex()}
                                   for d, k in ((SIREN, 1), (SIREN, 2), (BOX, 1), (GAUGE, 1), (RELAY, 1))],
                       "lora_addr": {d: a for d, a in ADDR.items()}},
        "commands": commands(),
        "command_checks": command_checks(),
        "frames": good_frames,
        "frame_rejects": frame_rejects(good_frames),
        "sms": sms(),
        "verification": verification(),
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the checked-in file differs")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is stale: python -m Pukaar.scripts.protocol_vectors", file=sys.stderr)
            return 1
        print(f"{args.out} is current")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
