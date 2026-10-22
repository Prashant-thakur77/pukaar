"""The device protocol: one canonical codec and signer for every path a siren command takes.

The firmware (C, mbedTLS) and this module must agree byte for byte. The golden vectors in
firmware/test/vectors/protocol_vectors.json are generated from this module
(python -m Pukaar.scripts.protocol_vectors) and the firmware's native tests read the same file.

Keys
    K_dev = HKDF-SHA256(ikm=root, salt="pukaar-device-root-v1", info="pukaar-dev|<device>|<kid>", L=32)
    The root is the SSM SecureString /pukaar/device_root (services/devices/keys.py). A device never
    derives: its own key and the keys of the senders it trusts are flashed at provisioning.

1. Shadow command (named shadow "siren", desired.cmd), docs/hardware/ALARM.md:
    canonical = "PKR1|" + id + "|" + device + "|" + action + "|" + pattern + "|" + clip + "|" +
                clip_sha256_16 + "|" + level + "|" + alert_id + "|" + cycles + "|" + repeat_every_s + "|" +
                repeat_cycles + "|" + cap_on_s + "|" + volume + "|" + iat + "|" + exp + "|" + ctr + "|" +
                src + "|" + kid
    Integers in decimal ASCII; an empty or missing string field is "-"; no field may contain "|".
    sig = base64url, no padding, of the first 16 bytes of HMAC-SHA256(K_dev, canonical): 22 characters.

2. LoRa P2P frame (binary, little-endian, at most 64 bytes):
    0 ver u8 = 1 | 1 type u8 | 2 src u16 | 4 dst u16 (0xFFFF broadcast) | 6 ctr u32 | 10 ts u32 (unix s, 0 unsynced)
    14 len u8 | 15 payload (len <= 40) | 15+len mac: the first 8 bytes of HMAC-SHA256(K_src, bytes[0 .. 15+len))
   SIREN_CMD_WRAPPED carries a compact command (20 bytes) and its own 16-byte signature with the
   siren's key over b"PKR1C|" + device + b"|" + compact; the outer MAC is the forwarder's. A relay or
   a box can carry a command but cannot make one.

3. Signed SMS (GSM-7, at most 160 characters):
    PKR1 <device> <A><L> <ctr, 6 digits or more> <exp, base36> <sig, Crockford base32, 16 chars>
    sig = the first 10 bytes of HMAC-SHA256(K_dev, "PKR1|<device>|<A>|<L>|<ctr>|<exp>"), ctr and exp
    in plain decimal. The prefix, codes and encodings are read in any case; the device id is exact.

4. relay_cmd (a pradhan box's "siren" shadow, desired.relay_cmd, one entry per siren of its village):
    {"<siren device id>": {"cmd_id", "dst": <the siren's LoRa address>, "exp", "payload": base64url (no
    padding) of the 36-byte SIREN_CMD_WRAPPED payload}}. The box sends the payload unchanged in a frame of
    its own (its outer MAC) to dst, once per command and only before exp. The inner signature is the
    siren's, so the box carries the command but cannot make or alter it.

Box events "report" (button A, water rising) and "ack" (button B, "mil gaya": the pradhan acknowledges
the alert the box shows, and the event carries that alert_id).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping

PROTO = "PKR1"
CMD_SIG_BYTES = 16
FRAME_MAC_BYTES = 8
SMS_SIG_BYTES = 10
INNER_SIG_BYTES = 16
HKDF_SALT = b"pukaar-device-root-v1"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

ACTIONS = ("sound", "stop", "test")
PATTERNS = ("W1", "C1", "A1", "T1", "D1")
CMD_LEVELS = ("warning", "critical", "all_clear", "test", "drill")
SOURCES = ("approval", "failsafe", "recall", "officer_manual", "pradhan_box", "key_switch", "autonomy",
           "schedule", "drill", "all_clear")
# The canonical string's fields, in order. The string fields may be "-" (empty).
CMD_FIELDS: tuple[str, ...] = ("id", "action", "pattern", "clip", "clip_sha256_16", "level", "alert_id",
                               "cycles", "repeat_every_s", "repeat_cycles", "cap_on_s", "volume", "iat", "exp",
                               "ctr", "src", "kid")
CMD_INT_FIELDS = {"cycles", "repeat_every_s", "repeat_cycles", "cap_on_s", "volume", "iat", "exp", "ctr", "kid"}
_PRINTABLE = re.compile(r"^[\x21-\x7e]{1,96}$")  # visible ASCII, no spaces


class ProtocolError(ValueError):
    """A field, frame or message that cannot be encoded or decoded."""


# -- keys ----------------------------------------------------------------------------------------
def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF with SHA-256."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def derive_device_key(root: bytes, device_id: str, kid: int = 1) -> bytes:
    """K_dev for one device and key id. In memory only: never logged, never stored server side."""
    if not root:
        raise ProtocolError("no root secret")
    return hkdf_sha256(root, HKDF_SALT, f"pukaar-dev|{device_id}|{int(kid)}".encode(), 32)


def _mac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]*", text or ""):
        raise ProtocolError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# -- 1. shadow command -----------------------------------------------------------------------------
def _field(name: str, value: Any) -> str:
    if name in CMD_INT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
            raise ProtocolError(f"{name} must be an integer from 0 to 2^32-1")
        return str(value)
    if value is None or value == "":
        return "-"
    text = str(value)
    if not _PRINTABLE.match(text) or "|" in text:
        raise ProtocolError(f"{name} must be 1-96 visible ASCII characters without '|'")
    return text


def canonical_command(cmd: Mapping[str, Any], device: str) -> str:
    """The string a siren command is signed over (spec 5.1). `device` is the thing name it is for."""
    parts = [PROTO, _field("id", cmd.get("id")), _field("device", device)]
    parts += [_field(name, cmd.get(name)) for name in CMD_FIELDS[1:]]
    return "|".join(parts)


def sign_command(key: bytes, cmd: Mapping[str, Any], device: str) -> str:
    return b64url(_mac(key, canonical_command(cmd, device).encode("ascii"))[:CMD_SIG_BYTES])


def command_sig_ok(key: bytes, cmd: Mapping[str, Any], device: str) -> bool:
    try:
        expected = sign_command(key, cmd, device)
    except ProtocolError:
        return False
    return hmac.compare_digest(expected, str(cmd.get("sig") or ""))


# -- 2. LoRa frames --------------------------------------------------------------------------------
FRAME_VERSION = 1
FRAME_MAX = 64
PAYLOAD_MAX = 40
BROADCAST = 0xFFFF
_HEADER = struct.Struct("<BBHHIIB")  # 15 bytes


class FrameType(IntEnum):
    GAUGE_STATUS = 0x01
    GAUGE_ALARM = 0x02
    SIREN_CMD_WRAPPED = 0x10
    SIREN_EVENT = 0x11
    BUTTON = 0x20
    HEARTBEAT = 0x30
    RELAY_BEACON = 0x31
    ACK = 0x7F


# (struct format, field names). Byte strings (cmd_id48, sig16) are bytes here, hex in the vectors.
PAYLOADS: dict[int, tuple[str, tuple[str, ...]]] = {
    FrameType.GAUGE_STATUS: ("<BhhBBH", ("level", "stage_cm", "rise_10min_cm", "quality", "cloud_ok",
                                         "rain_15min_tenths_mm")),
    FrameType.GAUGE_ALARM: ("<BhhBBH", ("level", "stage_cm", "rise_10min_cm", "quality", "cloud_ok",
                                        "rain_15min_tenths_mm")),
    FrameType.SIREN_CMD_WRAPPED: ("<6sBBBBHII16s", ("cmd_id48", "action", "pattern", "level", "cycles", "cap_on_s",
                                                    "exp", "ctr", "sig16")),
    FrameType.SIREN_EVENT: ("<B6sBBB", ("type", "cmd_id48", "verified", "amp_a_x10", "spl_rise_db")),
    FrameType.BUTTON: ("<BBH", ("button", "key_pos", "hold_ms")),
    FrameType.HEARTBEAT: ("<BBHHH", ("state", "soc", "batt_dv", "faults", "outbox")),
    FrameType.RELAY_BEACON: ("<HHBb", ("bus_dv", "bus_ma", "soc", "noise_dbm")),
    FrameType.ACK: ("<HI", ("acked_src", "acked_ctr")),
}
# Enumerations carried in frames (also in the vectors' "enums").
LEVEL_CODES = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}
ACTION_CODES = {"sound": 1, "stop": 2, "test": 3}
PATTERN_CODES = {"-": 0, "W1": 1, "C1": 2, "A1": 3, "T1": 4, "D1": 5}
CMD_LEVEL_CODES = {"-": 0, "warning": 2, "critical": 3, "all_clear": 4, "test": 5, "drill": 6}
BUTTON_CODES = {"water_rising": 1, "ack": 2, "siren": 3, "stop": 4}
KEY_POS_CODES = {"off": 0, "warning": 1, "critical": 2}
STATE_CODES = {"idle": 0, "sounding": 1, "testing": 2, "manual": 3, "autonomous": 4, "fault": 5, "low_power": 6,
               "boot": 7}
EVENT_CODES = {"cmd_received": 1, "started": 2, "verified": 3, "not_verified": 4, "finished": 5, "stopped": 6,
               "rejected": 7, "test_result": 8, "manual_trigger": 9, "autonomous_trigger": 10,
               "gauge_alarm_heard": 11, "tamper": 12, "fault": 13, "power": 14, "config_applied": 15,
               "report": 16, "ack": 17}


def _rev(table: Mapping[str, int]) -> dict[int, str]:
    return {v: k for k, v in table.items()}


@dataclass(frozen=True)
class Frame:
    ver: int
    type: int
    src: int
    dst: int
    ctr: int
    ts: int
    payload: bytes
    mac: bytes

    @property
    def signed_bytes(self) -> bytes:
        return _HEADER.pack(self.ver, self.type, self.src, self.dst, self.ctr, self.ts, len(self.payload)) + self.payload

    def to_bytes(self) -> bytes:
        return self.signed_bytes + self.mac


def pack_payload(ftype: int, fields: Mapping[str, Any]) -> bytes:
    if ftype not in PAYLOADS:
        raise ProtocolError(f"unknown frame type 0x{ftype:02x}")
    fmt, names = PAYLOADS[ftype]
    try:
        return struct.pack(fmt, *(fields[n] for n in names))
    except (KeyError, struct.error) as exc:
        raise ProtocolError(f"payload for 0x{ftype:02x}: {exc}") from None


def unpack_payload(ftype: int, payload: bytes) -> dict[str, Any]:
    if ftype not in PAYLOADS:
        raise ProtocolError(f"unknown frame type 0x{ftype:02x}")
    fmt, names = PAYLOADS[ftype]
    if len(payload) != struct.calcsize(fmt):
        raise ProtocolError(f"payload for 0x{ftype:02x} is {len(payload)} bytes, not {struct.calcsize(fmt)}")
    return dict(zip(names, struct.unpack(fmt, payload)))


def encode_frame(key: bytes, *, ftype: int, src: int, dst: int, ctr: int, ts: int, payload: bytes) -> bytes:
    if len(payload) > PAYLOAD_MAX:
        raise ProtocolError(f"payload of {len(payload)} bytes is over {PAYLOAD_MAX}")
    try:
        head = _HEADER.pack(FRAME_VERSION, ftype, src, dst, ctr, ts, len(payload))
    except struct.error as exc:
        raise ProtocolError(f"header: {exc}") from None
    signed = head + payload
    return signed + _mac(key, signed)[:FRAME_MAC_BYTES]


def decode_frame(data: bytes) -> Frame:
    """Parse a frame (no MAC check). ProtocolError for anything malformed or truncated."""
    if len(data) > FRAME_MAX:
        raise ProtocolError(f"frame of {len(data)} bytes is over {FRAME_MAX}")
    if len(data) < _HEADER.size + FRAME_MAC_BYTES:
        raise ProtocolError("frame truncated")
    ver, ftype, src, dst, ctr, ts, n = _HEADER.unpack_from(data)
    if ver != FRAME_VERSION:
        raise ProtocolError(f"frame version {ver}")
    if n > PAYLOAD_MAX:
        raise ProtocolError(f"payload length {n} is over {PAYLOAD_MAX}")
    if len(data) != _HEADER.size + n + FRAME_MAC_BYTES:
        raise ProtocolError("frame length does not match its header")
    payload = data[_HEADER.size:_HEADER.size + n]
    return Frame(ver, ftype, src, dst, ctr, ts, payload, data[_HEADER.size + n:])


def frame_mac_ok(frame: Frame, key: bytes) -> bool:
    return hmac.compare_digest(_mac(key, frame.signed_bytes)[:FRAME_MAC_BYTES], frame.mac)


# -- the compact command inside SIREN_CMD_WRAPPED ----------------------------------------------------
_COMPACT = struct.Struct("<6sBBBBHII")  # 20 bytes


def cmd_id48(cmd_id: str) -> bytes:
    """6 bytes that name a cloud command on LoRa: the first 6 bytes of SHA-256(command id)."""
    return hashlib.sha256(str(cmd_id).encode("ascii")).digest()[:6]


def compact_command(key: bytes, cmd: Mapping[str, Any], device: str) -> bytes:
    """The 36-byte SIREN_CMD_WRAPPED payload: 20-byte body + 16-byte signature with the siren's key."""
    try:
        body = _COMPACT.pack(cmd_id48(cmd["id"]), ACTION_CODES[cmd["action"]], PATTERN_CODES[cmd.get("pattern") or "-"],
                             CMD_LEVEL_CODES[cmd.get("level") or "-"], int(cmd["cycles"]), int(cmd["cap_on_s"]),
                             int(cmd["exp"]), int(cmd["ctr"]))
    except (KeyError, struct.error, ValueError, TypeError) as exc:
        raise ProtocolError(f"compact command: {exc}") from None
    return body + _mac(key, b"PKR1C|" + device.encode("ascii") + b"|" + body)[:INNER_SIG_BYTES]


def open_compact_command(key: bytes, payload: bytes, device: str) -> dict[str, Any] | None:
    """The compact command's fields when its inner signature is the siren's own, else None."""
    if len(payload) != _COMPACT.size + INNER_SIG_BYTES:
        return None
    body, sig = payload[:_COMPACT.size], payload[_COMPACT.size:]
    if not hmac.compare_digest(_mac(key, b"PKR1C|" + device.encode("ascii") + b"|" + body)[:INNER_SIG_BYTES], sig):
        return None
    cid, action, pattern, level, cycles, cap, exp, ctr = _COMPACT.unpack(body)
    return {"cmd_id48": cid.hex(), "action": _rev(ACTION_CODES).get(action), "pattern": _rev(PATTERN_CODES).get(pattern),
            "level": _rev(CMD_LEVEL_CODES).get(level), "cycles": cycles, "cap_on_s": cap, "exp": exp, "ctr": ctr}


def relay_cmd(key: bytes, cmd: Mapping[str, Any], device: str, dst: int) -> dict[str, Any]:
    """One relay_cmd entry for a pradhan box's shadow: the compact command for `device` (signed with that
    siren's key) and where to send it. ProtocolError if it does not fit the compact form."""
    if not 0 < int(dst) < BROADCAST:
        raise ProtocolError("relay_cmd needs the siren's own LoRa address")
    return {"cmd_id": str(cmd["id"]), "dst": int(dst), "exp": int(cmd["exp"]),
            "payload": b64url(compact_command(key, cmd, device))}


# -- 3. signed SMS --------------------------------------------------------------------------------------
SMS_ACTIONS = {"sound": "S", "stop": "X", "test": "T"}
SMS_LEVELS = {"warning": "W", "critical": "C", "all_clear": "A", "test": "T", "drill": "D"}
SMS_MAX = 160
_SMS = re.compile(r"^PKR1 ([A-Za-z0-9_.-]{3,64}) ([SXT])([WCATD]) (\d{1,10}) ([0-9A-Z]{1,7}) ([0-9A-Z]{16})$")


def crockford32(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    n = (len(data) * 8 + 4) // 5
    pad = n * 5 - len(data) * 8
    bits <<= pad
    return "".join(CROCKFORD[(bits >> (5 * (n - 1 - i))) & 31] for i in range(n))


def crockford32_decode(text: str, nbytes: int) -> bytes:
    text = text.upper().replace("O", "0").replace("I", "1").replace("L", "1")
    bits = 0
    for ch in text:
        if ch not in CROCKFORD:
            raise ProtocolError("not Crockford base32")
        bits = (bits << 5) | CROCKFORD.index(ch)
    bits >>= len(text) * 5 - nbytes * 8
    return bits.to_bytes(nbytes, "big")


def base36(n: int) -> str:
    if n < 0:
        raise ProtocolError("negative")
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = B36[r] + out
        if n == 0:
            return out


def sms_signing_string(device: str, action_code: str, level_code: str, ctr: int, exp: int) -> str:
    return f"{PROTO}|{device}|{action_code}|{level_code}|{int(ctr)}|{int(exp)}"


def sms_text(key: bytes, device: str, action: str, level: str, ctr: int, exp: int) -> str:
    a, lv = SMS_ACTIONS[action], SMS_LEVELS[level]
    sig = crockford32(_mac(key, sms_signing_string(device, a, lv, ctr, exp).encode("ascii"))[:SMS_SIG_BYTES])
    text = f"{PROTO} {device} {a}{lv} {int(ctr):06d} {base36(int(exp))} {sig}"
    if len(text) > SMS_MAX:
        raise ProtocolError("SMS over 160 characters")
    return text


@dataclass(frozen=True)
class SmsCommand:
    device: str
    action: str
    level: str
    ctr: int
    exp: int
    sig: str


def parse_sms(text: str) -> SmsCommand:
    """Read a signed SMS. ProtocolError when malformed, not ASCII, or over 160 characters."""
    if not isinstance(text, str) or len(text) > SMS_MAX:
        raise ProtocolError("missing or over 160 characters")
    if not text.isascii():
        raise ProtocolError("not GSM-7 ASCII")
    words = text.strip().split(" ")
    if len(words) != 6:
        raise ProtocolError("malformed")
    # The prefix, codes and encodings in any case (a phone may capitalise); the device id exactly.
    norm = " ".join([words[0].upper(), words[1], words[2].upper(), words[3], words[4].upper(), words[5].upper()])
    m = _SMS.match(norm)
    if not m:
        raise ProtocolError("malformed")
    device, a, lv, ctr, exp36, sig = m.groups()
    if int(ctr) > 0xFFFFFFFF or int(exp36, 36) > 0xFFFFFFFF:
        raise ProtocolError("counter or expiry out of range")
    action = {v: k for k, v in SMS_ACTIONS.items()}[a]
    level = {v: k for k, v in SMS_LEVELS.items()}[lv]
    return SmsCommand(device, action, level, int(ctr), int(exp36, 36), sig)


def sms_sig_ok(key: bytes, sms: SmsCommand) -> bool:
    signing = sms_signing_string(sms.device, SMS_ACTIONS[sms.action], SMS_LEVELS[sms.level], sms.ctr, sms.exp)
    expected = _mac(key, signing.encode("ascii"))[:SMS_SIG_BYTES]
    try:
        got = crockford32_decode(sms.sig, SMS_SIG_BYTES)
    except ProtocolError:
        return False
    return hmac.compare_digest(expected, got)


def sender_hash(salt: str, e164: str) -> str:
    """sha256(salt + E.164), hex: the only form a phone number takes in a device's config shadow."""
    return hashlib.sha256((salt + e164).encode("utf-8")).hexdigest()
