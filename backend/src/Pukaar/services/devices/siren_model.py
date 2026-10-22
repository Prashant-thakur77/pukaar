"""A pure-Python reference of what a siren node checks before it sounds, and of "verified".

The firmware implements the same rules in C; the tests and the siren simulator
(scripts/siren_sim_mqtt.py) run this one. Nothing here touches the network or the table.

Command acceptance, in order (docs/hardware/ALARM.md):
  1. the signature is valid with the key of cmd.kid           else "bad_sig" ("wrong_kid" for an unknown kid)
  2. cmd.id is not among the last 32 ids, and cmd.ctr is above the last counter seen on the same path
     (mqtt, sms or lora)                                           else "replayed"
  3. clock synced: now <= cmd.exp                                  else "expired"
     clock unsynced: cmd.exp within 12 h of the last known time    else "exp_window"
Receive counters (the last ctr accepted per path, and per sender for frames) are written through to
NVS when a message is accepted, before the device acts on it, and restored EXACTLY on boot. No bump:
a bump would make a siren that rebooted (floods cut power) refuse its gauge's next GAUGE_ALARM
frames, exactly when edge autonomy matters. The one gap, power lost after the accept but before the
write, can let that one message be accepted a second time. The existing checks bound it: a command's
expiry (at most 30 minutes) and a frame's 900 s time window keep an old capture out, and the ring of
recent command ids (persisted with the counters) stops the same command arriving again on another path.
Send counters (a device's own outgoing frame ctr) are the other way round: they are batched, so on
boot the stored value is raised by SEND_CTR_BOOT_SKIP and a counter is never reused after an unclean
shutdown. The server's per-device command ctr is an atomic DynamoDB ADD and needs no skip.

Frames: the sender is configured for the frame type's role, the MAC is valid with the sender's key,
the counter is above the last one from that sender, and |ts - now| < 900 s when both clocks are synced.

Verified (the sound really came out, not only "dispatched"): the amplifier current within
0.6 to 1.5 times its reference, and the microphone's rise of at least spl_rise_min_db over the 2 s
before, unless the microphone is known dead (fault "mic_dead"), when the current alone decides.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping

from Pukaar.services.devices import protocol as p

RECENT_IDS = 32
SEND_CTR_BOOT_SKIP = 16  # send counters only; receive counters are restored exactly
UNSYNCED_EXP_WINDOW_S = 12 * 3600
FRAME_SKEW_S = 900
VIAS = ("mqtt", "sms", "lora")

# Pattern defaults (spec 4.1): cycles in the first burst, repeat period and cycles while active, the cap
# per alert in sound-on seconds, and the volume in percent.
PATTERN_DEFAULTS: dict[str, dict[str, int]] = {
    "W1": {"cycles": 5, "repeat_every_s": 900, "repeat_cycles": 2, "cap_on_s": 1200, "volume": 100},
    "C1": {"cycles": 10, "repeat_every_s": 600, "repeat_cycles": 3, "cap_on_s": 2700, "volume": 100},
    "A1": {"cycles": 1, "repeat_every_s": 300, "repeat_cycles": 1, "cap_on_s": 120, "volume": 100},
    "T1": {"cycles": 1, "repeat_every_s": 0, "repeat_cycles": 0, "cap_on_s": 30, "volume": 50},
    "D1": {"cycles": 1, "repeat_every_s": 0, "repeat_cycles": 0, "cap_on_s": 120, "volume": 100},
}
PATTERN_LEVEL = {"W1": "warning", "C1": "critical", "A1": "all_clear", "T1": "test", "D1": "drill"}
# A lower priority never interrupts a higher one (spec 4.1).
PRIORITY = {"C1": 7, "autonomy": 6, "manual_critical": 5, "W1": 4, "manual_warning": 3, "A1": 2, "D1": 1, "T1": 0}
AMP_LOW, AMP_HIGH = 0.6, 1.5


def is_verified(meas: Mapping[str, Any] | None, *, amp_a_ref: float = 3.3, spl_rise_min_db: float = 15.0,
                faults: list[str] | tuple[str, ...] = ()) -> bool:
    """Current within 0.6-1.5 x the reference AND (the microphone heard it OR the microphone is known dead)."""
    if not meas:
        return False
    amp = meas.get("amp_a")
    if not isinstance(amp, (int, float)) or isinstance(amp, bool) or amp_a_ref <= 0:
        return False
    if not (AMP_LOW * amp_a_ref <= float(amp) <= AMP_HIGH * amp_a_ref):
        return False
    if "mic_dead" in faults:
        return True
    rise = meas.get("spl_rise_db")
    return isinstance(rise, (int, float)) and not isinstance(rise, bool) and float(rise) >= spl_rise_min_db


@dataclass
class CommandVerifier:
    """The siren's command checks, with its persistent state (counters per path, recent ids)."""

    device_id: str
    keys: dict[int, bytes]
    last_ctr: dict[str, int] = field(default_factory=lambda: {v: 0 for v in VIAS})
    recent_ids: deque = field(default_factory=lambda: deque(maxlen=RECENT_IDS))
    last_known_time: int = 0

    def persisted(self) -> dict[str, Any]:
        return {"last_ctr": dict(self.last_ctr), "recent_ids": list(self.recent_ids),
                "last_known_time": self.last_known_time}

    @classmethod
    def after_boot(cls, device_id: str, keys: dict[int, bytes], stored: Mapping[str, Any]) -> "CommandVerifier":
        """Restore from NVS exactly (receive counters are written through on accept; no bump)."""
        v = cls(device_id, dict(keys))
        for via, ctr in (stored.get("last_ctr") or {}).items():
            v.last_ctr[via] = int(ctr)
        v.recent_ids.extend(stored.get("recent_ids") or [])
        v.last_known_time = int(stored.get("last_known_time") or 0)
        return v

    def _fresh(self, cmd_id: str, ctr: int, via: str) -> bool:
        return cmd_id not in self.recent_ids and ctr > self.last_ctr.get(via, 0)

    def _expiry(self, exp: int, now: int | None) -> str | None:
        if now is not None:
            return "expired" if now > exp else None
        if exp > self.last_known_time + UNSYNCED_EXP_WINDOW_S:
            return "exp_window"
        return None

    def _accept(self, cmd_id: str, ctr: int, via: str, now: int | None) -> None:
        self.last_ctr[via] = ctr
        self.recent_ids.append(cmd_id)
        if now is not None:
            self.last_known_time = max(self.last_known_time, now)

    def accept(self, cmd: Mapping[str, Any], via: str, now: int | None) -> tuple[bool, str]:
        """A shadow (mqtt) or LoRa-delivered full command. now None: the clock is not synced."""
        kid = cmd.get("kid")
        key = self.keys.get(kid) if isinstance(kid, int) else None
        if key is None:
            return False, "wrong_kid"
        if not p.command_sig_ok(key, cmd, self.device_id):
            return False, "bad_sig"
        if not self._fresh(str(cmd["id"]), int(cmd["ctr"]), via):
            return False, "replayed"
        why = self._expiry(int(cmd["exp"]), now)
        if why:
            return False, why
        self._accept(str(cmd["id"]), int(cmd["ctr"]), via, now)
        return True, "ok"

    def accept_sms(self, text: str, *, sender_allowed: bool, now: int | None, kid: int = 1) -> tuple[bool, str]:
        """The SMS path: the sender's number hash first, then the same checks."""
        if not sender_allowed:
            return False, "sender"
        try:
            sms = p.parse_sms(text)
        except p.ProtocolError:
            return False, "malformed"
        key = self.keys.get(kid)
        if sms.device != self.device_id or key is None or not p.sms_sig_ok(key, sms):
            return False, "bad_sig"
        sms_id = f"sms:{sms.ctr}"
        if not self._fresh(sms_id, sms.ctr, "sms"):
            return False, "replayed"
        why = self._expiry(sms.exp, now)
        if why:
            return False, why
        self._accept(sms_id, sms.ctr, "sms", now)
        return True, "ok"


ROLE_FOR_TYPE = {
    p.FrameType.GAUGE_STATUS: "gauge_status", p.FrameType.GAUGE_ALARM: "gauge_alarm",
    p.FrameType.SIREN_CMD_WRAPPED: "relay_cmd", p.FrameType.SIREN_EVENT: "siren_event",
    p.FrameType.BUTTON: "button", p.FrameType.HEARTBEAT: "heartbeat", p.FrameType.RELAY_BEACON: "beacon",
    p.FrameType.ACK: "ack",
}


@dataclass
class Sender:
    device_id: str
    key: bytes
    roles: tuple[str, ...]


@dataclass
class FrameVerifier:
    """A LoRa receiver's checks. senders: {lora address: Sender}."""

    senders: dict[int, Sender]
    last_ctr: dict[int, int] = field(default_factory=dict)

    def persisted(self) -> dict[int, int]:
        return dict(self.last_ctr)

    @classmethod
    def after_boot(cls, senders: dict[int, Sender], stored: Mapping[int, int]) -> "FrameVerifier":
        """Restore the per-sender counters exactly: they were written through when each frame was accepted."""
        return cls(dict(senders), {int(src): int(ctr) for src, ctr in stored.items()})

    def accept(self, data: bytes, now: int | None) -> tuple[bool, str, p.Frame | None]:
        try:
            frame = p.decode_frame(data)
        except p.ProtocolError:
            return False, "malformed", None
        sender = self.senders.get(frame.src)
        if sender is None:
            return False, "unknown_src", frame
        role = ROLE_FOR_TYPE.get(frame.type)
        if role is None or role not in sender.roles:
            return False, "role", frame
        if not p.frame_mac_ok(frame, sender.key):
            return False, "bad_mac", frame
        if frame.ctr <= self.last_ctr.get(frame.src, 0):
            return False, "replayed", frame
        if now is not None and frame.ts and abs(frame.ts - now) >= FRAME_SKEW_S:
            return False, "clock_skew", frame
        self.last_ctr[frame.src] = frame.ctr
        return True, "ok", frame
