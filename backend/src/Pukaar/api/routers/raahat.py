"""Pukaar Raahat routes (PLAN.md §2.3). Public and read-only so far: the relief pool."""

from __future__ import annotations

from fastapi import APIRouter

from Pukaar.raahat import chain

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
    return {**base, **(read or {})}
