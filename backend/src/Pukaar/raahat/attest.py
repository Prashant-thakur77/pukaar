"""Impact attestation (ImpactAttestation, PLAN.md Step 3): did the flood happen, and how badly?

Three attesters, each once per alert, each with the hash of its evidence (the evidence itself stays off chain):

- satellite: the Sentinel-2 before and after already behind /impact (scripts/build_satellite.py). Severity comes
  from the newly flooded share of the compared area: (water after - water before) / area compared; at least 0.5%
  is 3, 0.1% is 2, anything more is 1, none is 0 (thresholds illustrative, for a valley-sized crop). The evidence
  hash is keccak256 of the public after-flood water-mask PNG, so anyone can re-hash it from the site. The imagery
  is the July 2023 Beas flood around Mandi town and Pandoh dam: only a replay of that flood, for a village inside
  the crop (Pandoh), is attested from it; any other alert is refused as no_satellite_coverage.
- officer: a district officer's severity and note; the evidence hash is keccak256 of the note with the alert id,
  the officer and the time, and the note is kept in the table.
- pradhan: the village's pradhan, from a verified photo report of their own village, of the same kind as the alert
  (replay or live), made at most EVIDENCE_WINDOW before it and used for no other attestation; the evidence hash
  is keccak256 of the photo's S3 object.

Two different keys at severity 2 or more confirm the flood (the contract counts keys, not roles), which opens the
confirmed tranche (relief.py tier 2). Cedar attest_impact decides who may attest (api/routers/raahat.py). Each
attestation is claimed in the table first (RAAHAT#ALERT#<id> / ATTEST#<who>) so it is sent once.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Attr
from eth_utils import keccak

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.raahat import anchor, chain
from Pukaar.store.models import VERIFIED_STATES, Alert
from Pukaar.store.repo import ConflictError, Repo

PRADHAN, OFFICER, SATELLITE = 0, 1, 2
NAMES = {PRADHAN: "pradhan", OFFICER: "officer", SATELLITE: "satellite"}
SCENARIO = "himachal_2023_07"  # the replay the 2023 imagery belongs to
ROOT = Path(__file__).resolve().parents[4]
SATELLITE_DIR = ROOT / "frontend" / "public" / "satellite" / "2023"
EVIDENCE_FILE = get_settings().data_dir / "raahat" / "satellite_2023.json"
EVIDENCE_WINDOW = timedelta(hours=24)  # a pradhan's photo may be at most this much older than the alert


class AttestRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _client() -> chain.RaahatChain | None:
    cfg = chain.load_config()
    if cfg is None or "impact_attestation" not in cfg.addresses:
        return None
    return chain.RaahatChain(cfg, provider=chain._provider_for(cfg))


def severity_from_fraction(new_water_km2: float, compared_km2: float) -> int:
    if compared_km2 <= 0 or new_water_km2 <= 0:
        return 0
    share = new_water_km2 / compared_km2
    return 3 if share >= 0.005 else 2 if share >= 0.001 else 1


def bake() -> dict[str, Any]:
    """The satellite evidence from the committed imagery (write it with: python -m Pukaar.raahat.attest bake)."""
    scenes = json.loads((SATELLITE_DIR / "scenes.json").read_text(encoding="utf-8"))
    west, south, east, north = scenes["bounds"]
    villages = json.loads((ROOT / "data" / "villages.json").read_text(encoding="utf-8"))
    villages = villages if isinstance(villages, list) else villages.get("villages", [])
    covers = sorted(v["id"] for v in villages if west <= v["lon"] <= east and south <= v["lat"] <= north)
    out = []
    for s in sorted((s for s in scenes["scenes"] if s.get("role") == "after"), key=lambda s: s["date"]):
        area = s["water_area"]
        new = round(area["after_km2"] - area["before_km2"], 3)
        out.append({"date": s["date"], "scene_id": s["scene_id"], "water": s["water"], "compared_km2": area["compared_km2"],
                    "before_km2": area["before_km2"], "after_km2": area["after_km2"], "new_water_km2": new,
                    "severity": severity_from_fraction(new, area["compared_km2"]),
                    "evidence_hash": "0x" + keccak((SATELLITE_DIR / s["water"]).read_bytes()).hex(),
                    "public_path": f"/satellite/2023/{s['water']}"})
    return {"event": scenes.get("event"), "scenario": SCENARIO, "bounds": scenes["bounds"], "covers": covers,
            "scenes": out, "source": scenes.get("source")}


def evidence() -> dict[str, Any]:
    return json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))


def _satellite_scene(repo: Repo, alert: Alert) -> dict | None:
    ev = evidence()
    replay = repo.get_replay()
    if not alert.replay or alert.village_id not in ev["covers"] or getattr(replay, "scenario", None) != ev["scenario"]:
        return None
    return ev["scenes"][0] if ev["scenes"] else None  # the first look after the flood


def _attest(repo: Repo, alert: Alert, who: int, severity: int, evidence_hash: bytes, by: str,
            extra: dict[str, Any] | None = None) -> dict[str, Any]:
    client = _client()
    row = anchor.get(repo, alert.id)
    if client is None:
        raise AttestRefused("raahat_off")
    if not row or row.get("state") != "sent":
        raise AttestRefused("not_anchored")
    pk, sk = anchor.PK + alert.id, f"ATTEST#{NAMES[who]}"
    claim = {"pk": pk, "sk": sk, "state": "sending", "who": NAMES[who], "severity": severity, "by": by,
             "evidence_hash": "0x" + evidence_hash.hex(), "at": clock.iso(clock.now()), **(extra or {})}
    try:
        repo._put(claim, condition=Attr("pk").not_exists() | Attr("state").eq("failed"))
    except ConflictError:
        raise AttestRefused("already_attested") from None
    tx = client.attest(anchor.alert_key(alert.id), who, severity, evidence_hash, village_id=alert.village_id)
    state = {"mined": "sent", "pending": "pending"}.get(client.confirm(tx), "failed") if tx else "failed"
    repo._update(pk, sk, {"state": state, "tx": tx})
    repo.add_timeline(alert.id, "raahat_attest", f"{NAMES[who]} attested severity {severity} ({by}): {state}" +
                      (f"; tx {tx}" if tx else ""))
    if state != "failed":
        anchor.index(repo, alert)
    return {k: v for k, v in claim.items() if k not in {"pk", "sk"}} | {"state": state, "tx": tx}


def _alert(repo: Repo, alert_id: str) -> Alert:
    alert = repo.get_alert(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    return alert


def attest_satellite(repo: Repo, alert_id: str, *, by: str) -> dict[str, Any]:
    alert = _alert(repo, alert_id)
    scene = _satellite_scene(repo, alert)
    if scene is None:
        raise AttestRefused("no_satellite_coverage")
    return _attest(repo, alert, SATELLITE, scene["severity"], bytes.fromhex(scene["evidence_hash"][2:]), by,
                   {"scene": scene["scene_id"], "evidence_url": scene["public_path"]})


def attest_officer(repo: Repo, alert_id: str, *, severity: int, note: str, by: str) -> dict[str, Any]:
    alert = _alert(repo, alert_id)
    if not 0 <= severity <= 3:
        raise AttestRefused("bad_severity")
    note = note.strip()[:500]
    at = clock.iso(clock.now())
    digest = keccak(json.dumps({"alert": alert.id, "by": by, "at": at, "note": note}, sort_keys=True).encode())
    return _attest(repo, alert, OFFICER, severity, digest, by, {"note": note})


def attest_pradhan(repo: Repo, alert_id: str, *, report_id: str, severity: int, by: str) -> dict[str, Any]:
    from Pukaar.services import storage

    alert = _alert(repo, alert_id)
    if not 0 <= severity <= 3:
        raise AttestRefused("bad_severity")
    report = repo.get_report(report_id)
    if report is None or report.village_id != alert.village_id:
        raise AttestRefused("report_from_another_village")
    if report.state not in VERIFIED_STATES:
        raise AttestRefused("report_not_verified")
    if not report.photo_key:
        raise AttestRefused("report_has_no_photo")
    if bool(report.replay) != bool(alert.replay):
        raise AttestRefused("report_from_another_flood")  # a replay's (or demo) photo never attests a live alert
    if clock.parse(report.created_at) < clock.parse(alert.created_at) - EVIDENCE_WINDOW:
        raise AttestRefused("report_too_old")
    # One photo report is evidence for one attestation: claimed before the attestation, released if it is refused.
    try:
        repo._put({"pk": f"RAAHAT#EVIDENCE#{report.id}", "sk": "USED", "alert_id": alert.id, "by": by},
                  condition=Attr("pk").not_exists())
    except ConflictError:
        raise AttestRefused("report_already_used") from None
    photo, _ = storage.get_bytes(report.photo_key)
    try:
        return _attest(repo, alert, PRADHAN, severity, keccak(photo), by, {"report_id": report.id})
    except AttestRefused:
        repo.t.delete_item(Key={"pk": f"RAAHAT#EVIDENCE#{report.id}", "sk": "USED"})
        raise


def status(repo: Repo, alert_id: str) -> dict[str, Any]:
    """What the chain says, per attester, and whether the flood is confirmed; with the satellite's coverage."""
    alert = _alert(repo, alert_id)
    client = _client()
    onchain = client.read_attestations(anchor.alert_key(alert.id)) if client else None
    rows = {r["sk"].split("#", 1)[1]: anchor._plain(r) for r in repo._query(anchor.PK + alert.id, "ATTEST#")}
    att: dict[str, Any] = {}
    for who, name in NAMES.items():
        c = (onchain or {}).get("attestations", {}).get(who)
        r = rows.get(name)
        att[name] = None if not (c or r) else {
            "severity": c["severity"] if c else r.get("severity"), "on_chain": bool(c),
            "state": r.get("state") if r else "sent", "tx": r.get("tx") if r else None,
            "evidence_hash": c["evidence_hash"] if c else r.get("evidence_hash"),
            "evidence_url": r.get("evidence_url") if r else None, "at": r.get("at") if r else None}
    return {"alert_id": alert.id, "village_id": alert.village_id, "attestations": att,
            "confirmed": bool(onchain and onchain.get("confirmed")), "chain_reachable": onchain is not None,
            "satellite_covers": _satellite_scene(repo, alert) is not None}


def main(argv: list[str]) -> int:
    if argv[:1] == ["bake"]:
        EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_FILE.write_text(json.dumps(bake(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {EVIDENCE_FILE}")
        return 0
    if argv[:1] == ["setup"]:
        if get_settings().is_local:
            from Pukaar.core.local import start_local_aws

            start_local_aws()
        client = _client()
        if client is None:
            print("ImpactAttestation not configured.")
            return 2
        villages = json.loads((ROOT / "data" / "villages.json").read_text(encoding="utf-8"))
        villages = villages if isinstance(villages, list) else villages.get("villages", [])
        for line in client.setup_attesters([v["id"] for v in villages]):
            print(line)
        return 0
    print("usage: python -m Pukaar.raahat.attest bake|setup")
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
