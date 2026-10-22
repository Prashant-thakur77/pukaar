"""Payout receipts (ReliefPool.receipt, PLAN.md Step 3): the village's cash-out agent records that one household was
paid, with a Merkle proof of the household's salted hash and a hash of the UPI or cash-out reference.

households_for() lists a released alert's households for the pradhan: the salted hash, a first name for a
registered person (never the full name, phone or chat id) or "Demo household N", and the receipt if there is one.
record() is the pradhan's entry (Cedar record_receipt, own village): it checks a release went out, builds the
proof from the register snapshot written with the root (households.py), claims RECEIPT#<household> so a household
is receipted once per alert, and sends the receipt. Only keccak256 of the reference is kept, here and on chain.
On testnet the cash-out agent is the backend's own signer, holding the village's relief for the pradhan.
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr
from eth_utils import keccak

from Pukaar.core import clock
from Pukaar.raahat import anchor, chain, households, relief
from Pukaar.store.models import Alert
from Pukaar.store.repo import ConflictError, Repo


class ReceiptRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _client() -> chain.RaahatChain | None:
    return relief._client()


def _alert(repo: Repo, alert_id: str) -> Alert:
    alert = repo.get_alert(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    return alert


def _labels(repo: Repo, village_id: str) -> dict[str, tuple[str, bool]]:
    """household hash -> (label, is_demo). A first name only; demo households by number."""
    key = households.salt()
    if key is None:
        return {}
    names = {r.id: (r.name or "").split()[0] if (r.name or "").strip() else "—"
             for r in repo.list_recipients(village_id)}
    out = {}
    for no, demo in households.register(repo, village_id):
        h = "0x" + households.household_hash(village_id, no, key).hex()
        out[h] = (f"Demo household {int(no.rsplit('-', 1)[1])}", True) if demo else (names.get(no, "—"), False)
    return out


def households_for(repo: Repo, alert_id: str) -> list[dict[str, Any]]:
    alert = _alert(repo, alert_id)
    snap = households.snapshot(repo, alert.village_id)
    if snap is None:
        snap = households.ensure_snapshot(repo, alert.village_id, _client())
        if snap is None:
            raise ReceiptRefused("register_changed")
    labels = _labels(repo, alert.village_id)
    done = {r["sk"].split("#", 1)[1]: anchor._plain(r) for r in repo._query(anchor.PK + alert.id, "RECEIPT#")}
    rows = []
    for h in snap["hashes"]:
        label, demo = labels.get(h, ("—", False))
        r = done.get(h)
        rows.append({"household": h, "label": label, "demo": demo,
                     "receipt": {k: r.get(k) for k in ("state", "tx", "at")} if r else None})
    # registered people first, then the demo households in order
    return sorted(rows, key=lambda r: (r["demo"], int(r["label"].rsplit(" ", 1)[1]) if r["demo"] else 0, r["label"]))


def record(repo: Repo, alert_id: str, household: str, upi_ref: str, *, by: str) -> dict[str, Any]:
    alert = _alert(repo, alert_id)
    ref = (upi_ref or "").strip()
    if not ref:
        raise ReceiptRefused("no_reference")
    if not any((relief.get_release(repo, alert.id, t) or {}).get("state") == "sent" for t in relief.TIERS):
        raise ReceiptRefused("nothing_released")
    if households.snapshot(repo, alert.village_id) is None:
        households.ensure_snapshot(repo, alert.village_id, _client())
    tree = households.snapshot_tree(repo, alert.village_id)
    try:
        hh = bytes.fromhex(household.removeprefix("0x"))
    except ValueError:
        raise ReceiptRefused("household_not_in_village") from None
    if tree is None or hh not in tree.households:
        raise ReceiptRefused("household_not_in_village")
    proof = tree.proof(hh)
    client = _client()
    if client is None:
        raise ReceiptRefused("raahat_off")
    pk, sk = anchor.PK + alert.id, f"RECEIPT#0x{hh.hex()}"
    ref_hash = keccak(text=ref)
    claim = {"pk": pk, "sk": sk, "state": "sending", "household": "0x" + hh.hex(), "by": by,
             "upi_ref_hash": "0x" + ref_hash.hex(), "at": clock.iso(clock.now())}
    try:
        repo._put(claim, condition=Attr("pk").not_exists() | Attr("state").eq("failed"))
    except ConflictError:
        raise ReceiptRefused("already_receipted") from None
    tx = client.receipt(anchor.alert_key(alert.id), hh, proof, ref_hash)
    repo._update(pk, sk, {"state": "sent" if tx else "failed", "tx": tx})
    if tx:
        anchor.index(repo, alert)
    return {k: v for k, v in claim.items() if k not in {"pk", "sk"}} | {"state": "sent" if tx else "failed", "tx": tx}


def counts(repo: Repo, alert_id: str) -> int:
    """Receipts sent for an alert (for the ledger)."""
    return sum(1 for r in repo._query(anchor.PK + alert_id, "RECEIPT#") if r.get("state") == "sent")
