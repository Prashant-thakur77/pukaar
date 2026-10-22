"""The Raahat indexer: the chain's own record of the relief layer, copied into the table (PLAN.md Step 4).

Run by the 15-minute sweep (handlers/sweep.py). From a checkpoint (RAAHAT#INDEX / CHECKPOINT; first run: the
deployment's block), it reads the four contracts' events in windows of WINDOW blocks (the public Base RPC serves
at most 200 per call), at most MAX_WINDOWS per run so a long catch-up spreads over sweeps, and stops
CONFIRMATIONS blocks short of the head. Each event is stored once (RAAHAT#EVENT / <block>#<log index>); Funded
events add up to the donors and the money given (RAAHAT#INDEX / FUNDS). The pool as read now is kept too
(RAAHAT#INDEX / POOL), so /raahat/pool can show it, labelled cached, when the chain cannot be read.

The backend writes its own records when it sends (anchor.py, relief.py, attest.py, receipts.py); the indexer adds
what others did on chain (a donor's fund()) and the chain's own word on all of it. It never raises: a failure is
logged and counted (RaahatIndexFailed) and the next sweep goes on from the same checkpoint.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from Pukaar.core import clock
from Pukaar.core.log import get_logger, log, metric
from Pukaar.raahat import chain
from Pukaar.store.repo import Repo

_LOG = get_logger("raahat")
INDEX_PK = "RAAHAT#INDEX"
EVENT_PK = "RAAHAT#EVENT"
WINDOW = 200
MAX_WINDOWS = 15
CONFIRMATIONS = 2


def _client() -> chain.RaahatChain | None:
    return chain.client()


def _start_block(client: chain.RaahatChain) -> int:
    """The deployment's block (RAAHAT_FROM_BLOCK, else the deployment file), else the last ~day of blocks."""
    raw = os.environ.get("RAAHAT_FROM_BLOCK", "").strip()
    if raw:
        return int(raw)
    path = chain._deployment_file()
    if path is not None and Path(path).is_file():
        dep = json.loads(Path(path).read_text(encoding="utf-8"))
        if dep.get("deployed_at_block"):
            return int(dep["deployed_at_block"])
    head = client.latest_block() or 0
    return max(0, head - 43_200)


def _get(repo: Repo, sk: str) -> dict | None:
    item = repo._get(INDEX_PK, sk)
    return {k: (int(v) if isinstance(v, Decimal) else v) for k, v in item.items() if k not in {"pk", "sk"}} if item else None


def checkpoint(repo: Repo) -> int | None:
    row = _get(repo, "CHECKPOINT")
    return int(row["block"]) if row else None


def funds(repo: Repo) -> dict[str, Any]:
    row = _get(repo, "FUNDS") or {}
    return {"donors": len(row.get("donors") or []), "funded_wei": str(row.get("funded_wei") or "0"),
            "events": int(row.get("events") or 0)}


def pool_snapshot(repo: Repo) -> dict | None:
    row = _get(repo, "POOL")
    return json.loads(row["pool"]) | {"indexed_at": row["at"]} if row else None


def run(repo: Repo) -> dict[str, Any]:
    try:
        client = _client()
        if client is None:
            return {"skipped": "off"}
        head = client.latest_block()
        if head is None:
            metric("RaahatIndexFailed", 1)
            return {"skipped": "chain_unreachable"}
        last = checkpoint(repo)
        start = last + 1 if last is not None else _start_block(client)
        stop = head - CONFIRMATIONS
        stored, to_block = 0, last
        for _ in range(MAX_WINDOWS):
            if start > stop:
                break
            end = min(start + WINDOW - 1, stop)
            events = client.read_events(start, end)
            if events is None:  # this window is read again next time
                metric("RaahatIndexFailed", 1)
                break
            stored += _store(repo, events)
            repo._put({"pk": INDEX_PK, "sk": "CHECKPOINT", "block": end, "at": clock.iso(clock.now())})
            to_block, start = end, end + 1
        pool = client.read_pool()
        if pool is not None:
            repo._put({"pk": INDEX_PK, "sk": "POOL", "pool": json.dumps(pool), "at": clock.iso(clock.now())})
        return {"events": stored, "to_block": to_block, "head": head}
    except Exception as exc:
        log(_LOG, "raahat index failed", 40, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        metric("RaahatIndexFailed", 1)
        return {"skipped": f"error: {type(exc).__name__}"}


def _store(repo: Repo, events: list[dict]) -> int:
    n = 0
    for e in events:
        sk = f"{int(e['block']):012d}#{int(e['log_index']):04d}"
        if repo._get(EVENT_PK, sk):
            continue  # stored by an earlier run
        repo._put({"pk": EVENT_PK, "sk": sk, "event": e["event"], "tx": e["tx"], "block": int(e["block"]),
                   "args": json.dumps(e.get("args") or {})})
        n += 1
        if e["event"] == "Funded":
            f = _get(repo, "FUNDS") or {}
            donors = sorted(set(f.get("donors") or []) | {e["args"]["donor"]})
            total = int(f.get("funded_wei") or 0) + int(e["args"]["amount"])
            repo._put({"pk": INDEX_PK, "sk": "FUNDS", "donors": donors, "funded_wei": str(total),
                       "events": int(f.get("events") or 0) + 1})
    return n
