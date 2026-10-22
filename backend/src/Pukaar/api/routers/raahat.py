"""Pukaar Raahat routes (PLAN.md §2.3): the public pool, ledger and anchors; officers release and attest;
pradhans attest their own village and record its payout receipts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from Pukaar.api.auth import Allowed, require_user, resource_facts
from Pukaar.policy.guard import Principal, authorize
from Pukaar.raahat import anchor, attest, chain, receipts, relief
from Pukaar.store.repo import get_repo

router = APIRouter()


@router.get("/raahat/pool")
def pool() -> dict:
    """The pool as read from the chain now. Always 200: when the chain cannot be read the page still gets the
    chain and the addresses, so the browser can try the chain itself and say honestly what failed."""
    cfg = chain.load_config()
    if cfg is None:
        return {"configured": False}
    read = chain.RaahatChain(cfg, provider=chain._provider_for(cfg)).read_pool()
    base = {"configured": True, "reachable": read is not None, "chain_id": cfg.chain_id, "network": cfg.network,
            "explorer": chain.explorer_url(cfg.chain_id), "public_rpc_url": cfg.public_rpc_url,
            "addresses": cfg.addresses, "pool_is_contract": cfg.pool_is_contract}
    from Pukaar.raahat.relief import ILLUSTRATIVE

    return {**base, **(read or {}), "illustrative": ILLUSTRATIVE}


@router.get("/raahat/alerts/{alert_id}")
def alert_anchor(alert_id: str) -> dict:
    """An alert's chain anchor: the CAP hash and URL, the transactions, the outcome counts. Ids and hashes only."""
    view = anchor.public_view(get_repo(), alert_id)
    if view is None:
        raise HTTPException(404, "This alert is not anchored")
    cfg = chain.load_config()  # the browser re-reads the record through the chain's public endpoint
    return {**view, "public_rpc_url": cfg.public_rpc_url if cfg and cfg.chain_id == view.get("chain_id") else None}


@router.get("/raahat/ledger")
def ledger(village_id: str = "") -> dict:
    """Public: the relief ledger (anchors, outcomes, releases), newest first. No names, no officer usernames."""
    return relief.ledger(get_repo(), village_id)


@router.get("/raahat/alerts/{alert_id}/relief")
def relief_status(alert_id: str, principal: Principal = Depends(Allowed("view_console", "alert", "alert_id"))) -> dict:
    """Officer console: per tier, eligible or why not (reason codes), households, amount and total."""
    try:
        return relief.status(get_repo(), alert_id)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None


class ReleaseBody(BaseModel):
    tier: int


@router.post("/raahat/alerts/{alert_id}/release")
def release(alert_id: str, body: ReleaseBody,
            principal: Principal = Depends(Allowed("release_relief", "alert", "alert_id"))) -> dict:
    """One tap by a district officer (Cedar release_relief, audited). 409 with a reason code when not eligible;
    502 when the chain refused or could not be reached (try again)."""
    try:
        out = relief.release(get_repo(), alert_id, body.tier, by=principal.username)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    except relief.ReliefRefused as exc:
        raise HTTPException(409, {"code": exc.code}) from None
    if out["state"] != "sent":
        raise HTTPException(502, {"code": "chain_failed", "release": out})
    return out


@router.get("/raahat/alerts/{alert_id}/attestations")
def attestations(alert_id: str) -> dict:
    """Public: the three attesters (severity, evidence hash, transaction) and whether the flood is confirmed."""
    try:
        return attest.status(get_repo(), alert_id)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None


class AttestBody(BaseModel):
    who: str  # "officer", "satellite" (run by an officer) or "pradhan"
    severity: int | None = None
    note: str = ""
    report_id: str = ""


@router.post("/raahat/alerts/{alert_id}/attest")
def attest_impact(alert_id: str, body: AttestBody,
                  principal: Principal = Depends(Allowed("attest_impact", "alert", "alert_id"))) -> dict:
    """Cedar attest_impact (officers any village, pradhans their own); each person attests only as themselves:
    an officer as the officer or by running the satellite check, a pradhan as the pradhan."""
    repo = get_repo()
    role = principal.role
    if (body.who in {"officer", "satellite"} and role != "officer") or (body.who == "pradhan" and role != "pradhan"):
        raise HTTPException(403, {"code": "denied", "reason": f"A {role} cannot attest as the {body.who}."})
    try:
        if body.who == "satellite":
            return attest.attest_satellite(repo, alert_id, by=principal.username)
        if body.severity is None:
            raise HTTPException(422, "severity (0 to 3) is required")
        if body.who == "officer":
            return attest.attest_officer(repo, alert_id, severity=body.severity, note=body.note, by=principal.username)
        if body.who == "pradhan":
            return attest.attest_pradhan(repo, alert_id, report_id=body.report_id, severity=body.severity,
                                         by=principal.username)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    except attest.AttestRefused as exc:
        raise HTTPException(409, {"code": exc.code}) from None
    raise HTTPException(422, "who must be officer, satellite or pradhan")


@router.get("/raahat/alerts/{alert_id}/households")
def alert_households(alert_id: str,
                     principal: Principal = Depends(Allowed("record_receipt", "alert", "alert_id"))) -> list[dict]:
    """The pradhan's list for receipts: salted household hashes, a first name or a demo label, receipt state."""
    try:
        return receipts.households_for(get_repo(), alert_id)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    except receipts.ReceiptRefused as exc:
        raise HTTPException(409, {"code": exc.code}) from None


class ReceiptBody(BaseModel):
    alert_id: str
    household: str
    upi_ref: str


@router.post("/raahat/receipts")
def record_receipt(body: ReceiptBody, principal: Principal = Depends(require_user)) -> dict:
    """A pradhan records that one household of their own village was paid (Cedar record_receipt on the alert in
    the body, audited like every decision). Only a hash of the UPI or cash reference is kept."""
    repo = get_repo()
    context = {"village_id": "", **resource_facts(repo, "alert", body.alert_id)}
    decision = authorize(principal, "record_receipt", "alert", body.alert_id, context, repo=repo)
    if not decision.allowed:
        raise HTTPException(403, {"code": "denied", "reason": decision.reason, "action": "record_receipt",
                                  "role": principal.role})
    try:
        out = receipts.record(repo, body.alert_id, body.household, body.upi_ref, by=principal.username)
    except KeyError:
        raise HTTPException(404, "Alert not found") from None
    except receipts.ReceiptRefused as exc:
        raise HTTPException(409, {"code": exc.code}) from None
    if out["state"] != "sent":
        raise HTTPException(502, {"code": "chain_failed"})
    return out
