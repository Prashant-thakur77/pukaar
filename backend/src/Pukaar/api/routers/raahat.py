"""Pukaar Raahat routes (PLAN.md §2.3). Public and read-only so far: the relief pool and alert anchors."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from Pukaar.api.auth import Allowed
from Pukaar.policy.guard import Principal
from Pukaar.raahat import anchor, chain, relief
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
