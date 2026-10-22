"""Anchoring alerts on the public chain (AlertRegistry, PLAN.md Step 1).

on_delivered: when an alert first reaches anyone (deliver, auto-send or the failsafe broadcast), the CAP 1.2
XML that /cap/alerts/{id}.xml serves is hashed and anchored with the village, level, issue time and the
exercise flag (replays and drills, as CAP status=Exercise). on_close: the delivered and acknowledged counts
and the hash of the after-action report. A failed alert anchor is tried once more at close.

Both are hooks the workflow calls and both never raise: a chain or code failure is logged, counted
(RaahatTxFailed, alarmed) and the alert carries on exactly as it would without Raahat. With Raahat not
configured (no RAAHAT_* settings, no AlertRegistry address) they do nothing at all.

Each send is claimed first with a conditional write on RAAHAT#ALERT#<id> / ANCHOR, so a re-run step, a
recall or a second Map batch never anchors twice. Ids, levels, counts and hashes only: nothing personal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr
from eth_utils import keccak

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.raahat import chain
from Pukaar.services import cap
from Pukaar.store.models import Alert
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("raahat")
PK, SK = "RAAHAT#ALERT#", "ANCHOR"
LEDGER_PK = "RAAHAT#LEDGER"  # one row per alert with a chain record, newest first by the alert's creation
LEVELS = {"watch": 1, "warning": 2, "critical": 3}
ZERO = b"\x00" * 32
PUBLIC_KEYS = ("alert_id", "alert_key", "village_id", "level", "exercise", "cap_hash", "cap_uri", "registry",
               "chain_id", "network", "tx", "state", "anchored_at", "outcome_tx", "outcome_state", "delivered",
               "acknowledged", "after_action_hash")


def alert_key(alert_id: str) -> bytes:
    return keccak(text=alert_id)


def cap_uri(alert_id: str) -> str:
    return f"{get_settings().api_url}/cap/alerts/{alert_id}.xml"


def cap_document(repo: Repo, alert: Alert) -> bytes:
    """The CAP XML exactly as GET /cap/alerts/{id}.xml renders it (api/routers/public.cap_alert)."""
    s = get_settings()
    refs = cap.references(alert, repo.list_alerts(village_id=alert.village_id, limit=100))
    return cap.render(alert, repo.get_village(alert.village_id), sender=s.cap_sender, web_url=s.web_url, refs=refs,
                      sender_name=s.cap_sender_name, sender_name_hi=s.cap_sender_name_hi)


def _plain(item: dict[str, Any]) -> dict[str, Any]:
    return {k: (int(v) if isinstance(v, Decimal) else v) for k, v in item.items() if k not in {"pk", "sk"}}


def get(repo: Repo, alert_id: str) -> dict[str, Any] | None:
    item = repo._get(PK + alert_id, SK)
    return _plain(item) if item else None


def public_view(repo: Repo, alert_id: str) -> dict[str, Any] | None:
    row = get(repo, alert_id)
    if row is None:
        return None
    view = {k: row.get(k) for k in PUBLIC_KEYS}
    view["explorer"] = chain.explorer_url(int(row.get("chain_id") or 0))
    return view


def index(repo: Repo, alert: Alert) -> None:
    repo._put({"pk": LEDGER_PK, "sk": f"{alert.created_at}#{alert.id}", "alert_id": alert.id,
               "village_id": alert.village_id})


def _client() -> chain.RaahatChain | None:
    cfg = chain.load_config()
    if cfg is None or "alert_registry" not in cfg.addresses:
        return None
    return chain.RaahatChain(cfg, provider=chain._provider_for(cfg))


def on_delivered(repo: Repo, alert_id: str) -> None:
    """Anchor the alert once it has reached someone. Never raises."""
    try:
        _anchor_alert(repo, alert_id)
    except Exception as exc:
        log(_LOG, "raahat anchor error", 40, alert_id=alert_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        metric("RaahatTxFailed", 1)


def on_close(repo: Repo, alert_id: str) -> None:
    """Anchor the outcome (and the alert, if its anchor failed). Never raises."""
    try:
        _anchor_outcome(repo, alert_id)
    except Exception as exc:
        log(_LOG, "raahat outcome error", 40, alert_id=alert_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        metric("RaahatTxFailed", 1)


def _anchor_alert(repo: Repo, alert_id: str, client: chain.RaahatChain | None = None, *, retry: bool = False) -> None:
    """retry: try again after a failed send (only close does, once); delivery never retries."""
    client = client or _client()
    if client is None:
        return
    alert = repo.get_alert(alert_id)
    if alert is None or not cap.is_published(alert) or alert.level not in LEVELS:
        return
    row = get(repo, alert_id)
    if row is not None and (row.get("state") != "failed" or not retry):
        return
    exercise = cap.is_exercise(alert)
    claim = {"state": "sending", "alert_id": alert.id, "alert_key": "0x" + alert_key(alert.id).hex(),
             "village_id": alert.village_id, "level": LEVELS[alert.level], "exercise": exercise,
             "registry": client.cfg.addresses["alert_registry"], "chain_id": client.cfg.chain_id,
             "network": client.cfg.network}
    try:
        if row is None:
            repo._put({"pk": PK + alert_id, "sk": SK, **claim}, condition=Attr("pk").not_exists())
        else:
            repo._update(PK + alert_id, SK, claim, condition=Attr("state").eq("failed"))
    except ConflictError:
        return  # another step is anchoring it, or already has
    xml = cap_document(repo, alert)
    record = (keccak(text=alert.village_id), LEVELS[alert.level], keccak(xml), cap_uri(alert.id),
              int(clock.parse(alert.created_at).timestamp()), exercise, 0, 0, ZERO)
    tx = client.anchor_alert(alert_key(alert.id), record)
    repo._update(PK + alert_id, SK, {"state": "sent" if tx else "failed", "tx": tx, "cap_hash": "0x" + keccak(xml).hex(),
                                    "cap_uri": cap_uri(alert.id), "anchored_at": clock.iso(clock.now())})
    if tx:
        index(repo, alert)
    repo.add_timeline(alert.id, "raahat_anchor",
                      f"anchored on {client.cfg.network}: tx {tx}" + (" (exercise)" if exercise else "") if tx
                      else f"chain anchor on {client.cfg.network} failed; the alert went out unchanged")


def _anchor_outcome(repo: Repo, alert_id: str) -> None:
    client = _client()
    if client is None:
        return
    alert = repo.get_alert(alert_id)
    if alert is None or not cap.is_published(alert):
        return
    row = get(repo, alert_id)
    if row is None or row.get("state") == "failed":
        _anchor_alert(repo, alert_id, client, retry=True)
        row = get(repo, alert_id)
    if row is None or row.get("state") != "sent":
        return  # the registry refuses an outcome for an alert it never saw
    try:
        repo._update(PK + alert_id, SK, {"outcome_state": "sending"},
                     condition=Attr("outcome_state").not_exists() | Attr("outcome_state").eq("failed"))
    except ConflictError:
        return
    from Pukaar.services import after_action

    report = after_action.load_stored(alert.id)
    report_hash = keccak(report.encode("utf-8")) if report else ZERO
    tx = client.anchor_outcome(alert_key(alert.id), alert.delivered_count, alert.acknowledged_count, report_hash)
    repo._update(PK + alert_id, SK, {"outcome_state": "sent" if tx else "failed", "outcome_tx": tx,
                                    "delivered": alert.delivered_count, "acknowledged": alert.acknowledged_count,
                                    "after_action_hash": "0x" + report_hash.hex()})
    repo.add_timeline(alert.id, "raahat_outcome",
                      f"outcome anchored on {client.cfg.network}: tx {tx}" if tx
                      else f"outcome anchor on {client.cfg.network} failed")
