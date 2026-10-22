"""The device protocol against its golden vectors (firmware/test/vectors/protocol_vectors.json).

The firmware's native tests read the same file; these prove the Python side reproduces every byte and
every decision in it, and that the checked-in file is what the generator makes today.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Pukaar.scripts import protocol_vectors as gen
from Pukaar.services.devices import protocol as p
from Pukaar.services.devices.siren_model import CommandVerifier, FrameVerifier, Sender, is_verified

VECTORS = Path(__file__).resolve().parents[2] / "firmware" / "test" / "vectors" / "protocol_vectors.json"
V = json.loads(VECTORS.read_text(encoding="utf-8"))


def test_the_checked_in_vectors_are_current_and_test_only():
    assert VECTORS.read_text(encoding="utf-8") == gen.render(), "python -m Pukaar.scripts.protocol_vectors"
    assert "TEST ONLY" in V["_warning"] and V["derivation"]["root_hex"] == bytes(range(32)).hex()
    assert gen.main(["--check"]) == 0


def test_key_derivation_is_hkdf_per_device_and_kid():
    root = bytes.fromhex(V["derivation"]["root_hex"])
    keys = set()
    for d in V["derivation"]["devices"]:
        key = p.derive_device_key(root, d["device"], d["kid"])
        assert key.hex() == d["key_hex"]
        keys.add(key)
    assert len(keys) == len(V["derivation"]["devices"])  # a new kid or another device: another key
    # RFC 5869 test case 1 (SHA-256), so the HKDF itself is the standard one.
    okm = p.hkdf_sha256(bytes.fromhex("0b" * 22), bytes.fromhex("000102030405060708090a0b0c"),
                        bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42)
    assert okm.hex() == ("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                         "34007208d5b887185865")


@pytest.mark.parametrize("case", V["commands"], ids=lambda c: c["name"])
def test_command_canonical_string_and_signature(case):
    key = bytes.fromhex(case["key_hex"])
    cmd = {k: v for k, v in case["cmd"].items() if k != "sig"}
    assert p.canonical_command(cmd, case["device"]) == case["canonical"]
    assert p.sign_command(key, cmd, case["device"]) == case["sig"] and len(case["sig"]) == 22
    assert p.command_sig_ok(key, case["cmd"], case["device"])
    assert not p.command_sig_ok(key, case["cmd"], "siren-thunag-02")  # bound to the device
    tampered = dict(case["cmd"], ctr=case["cmd"]["ctr"] + 1)
    assert not p.command_sig_ok(key, tampered, case["device"])


def test_command_fields_refuse_separators_and_non_integers():
    with pytest.raises(p.ProtocolError):
        p.canonical_command({"id": "a|b", "action": "sound", **{k: 1 for k in p.CMD_INT_FIELDS}}, "siren-x")
    with pytest.raises(p.ProtocolError):
        p.canonical_command({"id": "a", "action": "sound", "cycles": "5"}, "siren-x")


def _replay(seq):
    keys = {int(k): bytes.fromhex(v) for k, v in seq["keys_by_kid"].items()}
    if "stored_state" in seq:
        return CommandVerifier.after_boot(seq["device"], keys, seq["stored_state"])
    return CommandVerifier(seq["device"], keys)


@pytest.mark.parametrize("seq", V["command_checks"], ids=lambda s: s["name"])
def test_command_acceptance_sequences_replay_exactly(seq):
    v = _replay(seq)
    for step in seq["steps"]:
        assert v.accept(step["cmd"], step["via"], step["now"]) == (step["accept"], step["reason"]), step["label"]


def test_acceptance_matrix_covers_replay_expiry_kid_and_boot():
    reasons = {s["reason"] for seq in V["command_checks"] for s in seq["steps"]}
    assert {"ok", "replayed", "bad_sig", "wrong_kid", "expired", "exp_window"} <= reasons
    boot = next(s for s in V["command_checks"] if s["name"] == "boot_bump")
    assert [s["accept"] for s in boot["steps"]] == [False, True]  # the +16 on boot


@pytest.mark.parametrize("case", V["frames"], ids=lambda c: c["name"])
def test_frames_encode_and_decode_round_trip(case):
    key = bytes.fromhex(case["key_hex"])
    h = case["header"]
    payload = bytes.fromhex(case["payload_hex"])
    data = p.encode_frame(key, ftype=h["type"], src=h["src"], dst=h["dst"], ctr=h["ctr"], ts=h["ts"], payload=payload)
    assert data.hex() == case["frame_hex"] and len(data) <= p.FRAME_MAX
    frame = p.decode_frame(data)
    assert (frame.type, frame.src, frame.dst, frame.ctr, frame.ts) == (h["type"], h["src"], h["dst"], h["ctr"], h["ts"])
    assert p.frame_mac_ok(frame, key) and frame.mac.hex() == case["mac_hex"]
    fields = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in p.unpack_payload(h["type"], payload).items()}
    assert fields == case["payload_fields"]
    for cut in (1, len(data) - 1):
        with pytest.raises(p.ProtocolError):
            p.decode_frame(data[:cut])  # truncated


def test_the_wrapped_command_opens_only_with_the_sirens_key():
    case = next(f for f in V["frames"] if f["name"] == "siren_cmd_wrapped_by_box")
    payload = bytes.fromhex(case["payload_hex"])
    inner = case["inner"]
    assert p.open_compact_command(bytes.fromhex(inner["siren_key_hex"]), payload, inner["device"]) == inner["fields"]
    assert p.open_compact_command(bytes.fromhex(case["key_hex"]), payload, inner["device"]) is None  # the box's key


def test_frame_rejects_and_a_forwarder_cannot_forge():
    r = V["frame_rejects"][0]
    senders = {int(a, 16): Sender(s["device"], bytes.fromhex(s["key_hex"]), tuple(s["roles"]))
               for a, s in r["senders"].items()}
    v = FrameVerifier(senders)
    assert v.accept(bytes.fromhex(r["accepted_first"]["frame_hex"]), gen.NOW)[0]
    siren_key = p.derive_device_key(bytes(range(32)), r["receiver"])
    for case in r["cases"]:
        ok, reason, frame = v.accept(bytes.fromhex(case["frame_hex"]), case["now"])
        if case["expect_reason"] == "ok_outer_bad_inner":
            assert ok and p.open_compact_command(siren_key, frame.payload, r["receiver"]) is None
        else:
            assert (ok, reason) == (False, case["expect_reason"]), case["name"]


def test_signed_sms_texts_and_checks():
    for g in V["sms"]["good"]:
        key = bytes.fromhex(g["key_hex"])
        assert p.sms_text(key, g["device"], g["action"], g["level"], g["ctr"], g["exp"]) == g["text"]
        assert g["length"] <= 160 and g["text"].isascii()
        sms = p.parse_sms(g["text"])
        assert (sms.device, sms.action, sms.level, sms.ctr, sms.exp) == (g["device"], g["action"], g["level"],
                                                                          g["ctr"], g["exp"])
        assert p.sms_sig_ok(key, sms)
    key = bytes.fromhex(V["sms"]["good"][0]["key_hex"])
    v = CommandVerifier("siren-thunag-01", {1: key})
    assert v.accept_sms(V["sms"]["checks"]["first_accepted"], sender_allowed=True, now=gen.NOW) == (True, "ok")
    for c in V["sms"]["checks"]["cases"]:
        verifier = CommandVerifier("siren-thunag-01", {1: key}) if c["name"] == "case_insensitive_prefix" else v
        assert verifier.accept_sms(c["text"], sender_allowed=c["sender_allowed"], now=c["now"]) == (c["accept"], c["reason"]), c["name"]
    sh = V["sms"]["sender_hash"]
    assert p.sender_hash(sh["salt"], sh["e164"]) == sh["sha256_hex"]


@pytest.mark.parametrize("case", V["verification"], ids=lambda c: c["name"])
def test_verified_needs_current_and_the_microphone_or_a_known_mic_fault(case):
    assert is_verified(case["meas"], amp_a_ref=case["amp_a_ref"], spl_rise_min_db=case["spl_rise_min_db"],
                       faults=case["faults"]) is case["verified"]


def test_crockford_and_base36_round_trip():
    data = bytes(range(10))
    assert p.crockford32_decode(p.crockford32(data), 10) == data
    assert p.crockford32_decode(p.crockford32(data).lower(), 10) == data
    assert int(p.base36(1761123605), 36) == 1761123605
