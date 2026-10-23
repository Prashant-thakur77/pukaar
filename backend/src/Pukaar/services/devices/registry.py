"""The device registry (VILLAGE#<v> / DEVICE#<d>) and its health, which fails closed.

Health, computed on read so it is never stale (spec 5.7, after OpenFloodAI's UNKNOWN_DEGRADED):
  unknown   never heard from on any path. Never shown as OK.
  offline   nothing on any path (cell, LoRa, SMS) for more than OFFLINE_MINUTES.
  fault     the last test failed, an amplifier or siren-line fault, or the door tamper switch.
  degraded  SoC 15-50 %, a silent test overdue (TEST_OVERDUE_DAYS), the microphone dead while the current
            reads fine, heard over LoRa only, or a not-yet-installed device past its first contact.
  ok        heard within OK_MINUTES, a silent test passed in the last 8 days, SoC >= 50 %, no faults.
A gauge is "ok" on recent contact alone (its own health lives in services/gauge.py).

FloodNet-style checks (services/devices/floodnet.py), passed in as signals (device_signals reads them): a battery
that empties within a week at its slope ("battery_empty_in_<n>d"), more than 20% of readings missing from the
device's sequence numbers ("packet_loss_<pct>pct"), and the same value N times running while rain falls
("stuck_<n>_readings"). Each is a reason, and makes an otherwise ok device degraded.

Heartbeats update the registry with a condition on their time, so an older heartbeat never overwrites
a newer one. A heartbeat forwarded over LoRa sets last_seen_path "lora".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log
from Pukaar.store.models import Device, Village
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("devices")
OK_MINUTES = 15
OFFLINE_MINUTES = 20
TEST_OVERDUE_DAYS = 8
AUDIBLE_OVERDUE_DAYS = 35
FAULT_FAULTS = {"amp_open", "amp_short", "siren_line", "tamper", "sd_digest", "dfplayer"}
SOUNDERS = {"siren", "box"}  # what SirenOffline counts


def _minutes_since(at: str | None, now: datetime) -> float | None:
    if not at:
        return None
    return (now - clock.parse(at)).total_seconds() / 60


def test_overdue(d: Device, now: datetime) -> bool:
    if d.kind != "siren":
        return False
    t = d.last_test_silent or {}
    if not t.get("at") or not t.get("ok"):
        return True
    return now - clock.parse(str(t["at"])) > timedelta(days=TEST_OVERDUE_DAYS)


def health(d: Device, now: datetime | None = None, signals: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """(state, reasons). state is ok, degraded, offline, fault or unknown. signals: device_signals() (FloodNet)."""
    now = now or clock.now()
    seen = _minutes_since(d.last_seen, now)
    if seen is None:
        return "unknown", ["never_heard"]
    extra = list((signals or {}).get("reasons") or [])
    reasons: list[str] = []
    fault = [f for f in d.faults if f in FAULT_FAULTS]
    if d.tamper_at and (now - clock.parse(d.tamper_at)) < timedelta(days=1):
        fault.append("tamper")
    if d.kind == "siren" and d.last_test_silent and d.last_test_silent.get("ok") is False:
        fault.append("test_failed")
    if d.kind == "siren" and d.last_test_audible and d.last_test_audible.get("ok") is False and (
            not d.last_test_silent or str(d.last_test_audible.get("at", "")) >= str(d.last_test_silent.get("at", ""))):
        fault.append("audible_test_failed")
    if seen > OFFLINE_MINUTES:
        return "offline", [f"silent_{int(seen)}_min", *sorted(set(fault)), *extra]
    if fault:
        return "fault", [*sorted(set(fault)), *extra]
    if d.soc is not None and d.soc < 50:
        reasons.append(f"soc_{d.soc}")
    if test_overdue(d, now):
        reasons.append("test_overdue")
    if "mic_dead" in d.faults:
        reasons.append("mic_dead")
    if d.last_seen_path == "lora":
        reasons.append("lora_only")
    if seen > OK_MINUTES:
        reasons.append(f"late_{int(seen)}_min")
    other = [f for f in d.faults if f not in FAULT_FAULTS and f != "mic_dead"]
    reasons += [f"fault_{f}" for f in other]
    reasons += extra
    return ("degraded" if reasons else "ok"), reasons


def device_signals(repo: Repo, d: Device, now: datetime | None = None) -> dict[str, Any]:
    """The FloodNet checks for one device from what it already sent. A gauge or rain node: its own readings
    (battery, seq, the river level); a siren, box or relay: the heartbeat battery history. Never raises."""
    from Pukaar.services import risk_rules
    from Pukaar.services.devices import floodnet

    now = now or clock.now()
    try:
        if d.kind in {"gauge", "rain"}:
            since = clock.iso(now - timedelta(hours=floodnet.BATTERY_WINDOW_HOURS))
            rows = (repo.list_sensor_readings(d.village_id, since) if d.kind == "gauge"
                    else repo.list_rain_readings(d.village_id, since))
            rows = [r for r in rows if r.device_id == d.device_id]
            day = now - timedelta(hours=floodnet.PACKET_WINDOW_HOURS)
            seqs = [(r.boot, r.seq) for r in rows if clock.parse(r.at) >= day]
            battery = [(clock.parse(r.at), r.battery_v * 1000) for r in rows if r.battery_v is not None]
            empty = floodnet.EMPTY_MV
            values = None
            raining = False
            if d.kind == "gauge":
                v = repo.get_village(d.village_id)
                if v is not None and v.gauge is not None:
                    empty = float(v.gauge.low_battery_mv)
                latest = repo.list_readings(d.village_id, limit=1)
                reading = latest[0] if latest and not latest[0].replay else None
                raining = risk_rules.raining(reading, risk_rules.rain_level(reading.rain_24h_mm if reading else None),
                                             None) is not None
                values = [r.water_level_cm for r in rows if r.origin == "live" and r.quality == "good"]
            out = floodnet.signals(now=now, battery=battery, empty=empty, seqs=seqs, values=values, raining=raining)
        else:
            hist = d.batt_hist or []
            soc = [(clock.parse(str(h["at"])), float(h["soc"])) for h in hist if h.get("soc") is not None]
            mv = [(clock.parse(str(h["at"])), float(h["mv"])) for h in hist if h.get("mv") is not None]
            out = (floodnet.signals(now=now, battery=soc, empty=floodnet.EMPTY_SOC, unit="soc") if len(soc) >= len(mv)
                   and soc else floodnet.signals(now=now, battery=mv))
        return out
    except Exception as exc:
        log(_LOG, "device signals failed", 30, device_id=d.device_id, error=str(exc)[:200])
        return {"battery": None, "packet_loss": None, "stuck": None, "reasons": []}


def view(d: Device, now: datetime | None = None, *, public: bool = False,
         signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """The registry row and its health. Public: nothing an attacker could use (no SIM number, LoRa
    address, owner, allowed senders or command ids), and no alert id. signals: device_signals() (FloodNet)."""
    now = now or clock.now()
    state, reasons = health(d, now, signals)
    out = d.model_dump(exclude={"sim_number", "batt_hist"})
    out["health"], out["health_reasons"] = state, reasons
    if signals is not None:
        out["health_signals"] = {k: signals.get(k) for k in ("battery", "packet_loss", "stuck")}
    out["test_overdue"] = test_overdue(d, now)
    if public:
        for k in ("lora_addr", "owner_recipient_id", "allowed_senders", "autonomy", "pending_cmd", "kid",
                  "conn_version", "pour_test_until", "lat", "lon", "horn_azimuth_deg", "note", "test_schedule",
                  "amp_a_ref", "siren_a_ref", "spl_rise_min_db"):
            out.pop(k, None)
        if out.get("last_sound"):
            out["last_sound"] = {k: v for k, v in out["last_sound"].items() if k != "alert_id"}
    return out


def village_sirens(repo: Repo, village_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    """The public village page's one line: how many sirens, sounding now, and the last test. No ids."""
    now = now or clock.now()
    sirens = [d for d in repo.list_devices(village_id) if d.kind == "siren"]
    if not sirens:
        return None
    tests = [t for d in sirens for t in (d.last_test_audible, d.last_test_silent) if t and t.get("at")]
    last = max(tests, key=lambda t: str(t["at"])) if tests else None
    return {"count": len(sirens), "sounding": sum(1 for d in sirens if d.state in {"sounding", "manual", "autonomous"}),
            "last_test_at": last["at"] if last else None, "last_test_ok": bool(last["ok"]) if last else None,
            "overdue": any(test_overdue(d, now) for d in sirens),
            "simulated": all(d.simulated for d in sirens)}


def seed_village(repo: Repo, village: Village, raw_devices: list[dict[str, Any]]) -> list[str]:
    """Registry rows from data/villages.json, plus one for the village gauge. Live health is kept."""
    rows = [dict(r) for r in raw_devices]
    if village.gauge is not None and not any(r.get("device_id") == village.gauge.device_id for r in rows):
        rows.append({"device_id": village.gauge.device_id, "kind": "gauge", "installed": village.gauge.installed})
    out = []
    for raw in rows:
        existing = repo.get_device(raw["device_id"])
        fresh = Device.model_validate({**raw, "village_id": village.id,
                                       "simulated": bool(raw.get("simulated")) or raw["device_id"].endswith("-sim"),
                                       "created_at": existing.created_at if existing else clock.iso(clock.now())})
        if existing is not None:
            live = existing.model_dump(include={
                "last_seen", "last_seen_path", "connected", "conn_version", "state", "state_since", "soc", "batt_mv",
                "solar_wh_today", "rssi", "lora_noise_dbm", "temp_c", "outbox_depth", "faults", "last_test_silent",
                "last_test_audible", "last_sound", "tamper_at", "pending_cmd", "fw", "batt_hist"})
            fresh = fresh.model_copy(update={k: v for k, v in live.items() if v not in (None, [])})
        repo.put_device(fresh)
        out.append(fresh.device_id)
    return out


def apply_heartbeat(repo: Repo, d: Device, hb: dict[str, Any], at: str, *, path: str = "cell") -> Device | None:
    """Live health from a heartbeat; an older one than the stored last_seen changes nothing."""
    fields: dict[str, Any] = {"last_seen": at, "last_seen_path": path}
    for src, dst in (("soc", "soc"), ("batt_mv", "batt_mv"), ("solar_wh_today", "solar_wh_today"), ("rssi", "rssi"),
                     ("lora_noise_dbm", "lora_noise_dbm"), ("temp_c", "temp_c"), ("fw", "fw"),
                     ("outbox_depth", "outbox_depth"), ("state", "state")):
        if hb.get(src) is not None:
            fields[dst] = hb[src]
    if isinstance(hb.get("faults"), list):
        fields["faults"] = [str(f)[:24] for f in hb["faults"]][:16]
    if hb.get("state") and hb.get("state") != d.state:
        fields["state_since"] = at
    if hb.get("batt_mv") is not None or hb.get("soc") is not None:  # the FloodNet battery slope (floodnet.py)
        from Pukaar.services.devices import floodnet

        hist = floodnet.append_history(d.batt_hist, at, hb.get("batt_mv"), hb.get("soc"))
        if hist != d.batt_hist:
            fields["batt_hist"] = hist
    try:
        return repo.update_device(d.village_id, d.device_id,
                                  condition=Attr("last_seen").not_exists() | Attr("last_seen").lte(at), **fields)
    except ConflictError:
        return None


def touch(repo: Repo, village_id: str, device_id: str, at: str, path: str = "cell", **fields: Any) -> None:
    """Contact from a device (an event, a gauge reading). Never raises: a registry write must not lose a reading."""
    try:
        repo.update_device(village_id, device_id, condition=Attr("last_seen").not_exists() | Attr("last_seen").lte(at),
                           last_seen=at, last_seen_path=path, **fields)
    except ConflictError:
        pass
    except Exception as exc:
        log(_LOG, "device touch failed", 30, device_id=device_id, error=str(exc)[:200])


def apply_presence(repo: Repo, d: Device, connected: bool, at: str, version: int | None) -> Device | None:
    """$aws/events/presence: out of order and duplicated, so ordered by time. A disconnect alone never
    makes a device offline: offline is "nothing heard on any path for 20 minutes" (the grace)."""
    fields: dict[str, Any] = {"connected": connected}
    if version is not None:
        fields["conn_version"] = version
    if connected:
        fields.update(last_seen=at, last_seen_path="cell")
    cond = Attr("presence_at").not_exists() | Attr("presence_at").lte(at)
    try:
        return repo.update_device(d.village_id, d.device_id, condition=cond, presence_at=at, **fields)
    except ConflictError:
        return None
