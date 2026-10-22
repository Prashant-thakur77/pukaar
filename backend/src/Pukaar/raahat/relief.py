"""Relief release (PLAN.md Step 2): code decides eligibility, a district officer releases, the ReliefPool
contract enforces the sealed rule.

status() reads what the contract will check (the sealed rule, the village's households and cash-out agent,
the pool balance, earlier releases and the cooldown) and says, per tier, eligible or why not, as reason
codes the console words in Hindi and English. release() is the officer's one tap (Cedar release_relief,
api/routers/raahat.py): it re-checks, claims RAAHAT#ALERT#<id> / RELEASE#<tier> so a double tap sends one
transaction, sends ReliefPool.release and records the result. A sent release is put on the ledger, pushed
on /public/raahat (ids, tier and amounts only) and, for a live alert only, told to the village's registered
Telegram users as test money. Nothing here is on the alert path.

Amounts are illustrative (ILLUSTRATIVE): SDRF norms are to be mapped with the DDMA.
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr

from Pukaar.core import clock
from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log
from Pukaar.raahat import anchor, chain
from Pukaar.store.models import Alert
from Pukaar.store.repo import ConflictError, Repo

_LOG = get_logger("raahat")
ILLUSTRATIVE = "illustrative, SDRF norms to be mapped with DDMA"
TIERS = (1, 2)
WEI = 10**18


class ReliefRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _client() -> chain.RaahatChain | None:
    cfg = chain.load_config()
    if cfg is None or not cfg.pool_is_contract or "alert_registry" not in cfg.addresses:
        return None
    return chain.RaahatChain(cfg, provider=chain._provider_for(cfg))


def inr(wei: int | str) -> str:
    """Whole tINR with Indian digit grouping: 1500 -> "1,500", 150000 -> "1,50,000"."""
    n = str(int(wei) // WEI)
    if len(n) <= 3:
        return n
    head, tail = n[:-3], n[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail])


def get_release(repo: Repo, alert_id: str, tier: int) -> dict[str, Any] | None:
    item = repo._get(anchor.PK + alert_id, f"RELEASE#{tier}")
    return anchor._plain(item) if item else None


def _why(tier: int, alert: Alert, level: int, exercise: bool, s: dict, recorded: dict | None) -> list[str]:
    rule = s["rule"]
    amount = rule["amount_anticipatory_wei"] if tier == 1 else rule["amount_confirmed_wei"]
    why = []
    if not s["sealed"]:
        why.append("rules_not_sealed")
    if exercise and not s["allow_exercise"]:
        why.append("exercise_not_allowed")
    if s["released"].get(tier) or (recorded and recorded.get("state") in {"sent", "sending"}):
        why.append("already_released")
    if tier == 1:
        if level < rule["min_level"]:
            why.append("level_below_rule")
        last = int(s["last_anticipatory"] or 0)
        if last and s["now"] < last + int(rule["cooldown_hours"]) * 3600:
            why.append("cooldown")
    elif s["confirmed"] is not True:
        why.append("not_confirmed")
    if not s["households"]:
        why.append("no_households")
    if not s["agent"]:
        why.append("no_agent")
    if s["households"] and int(s["balance_wei"]) < int(s["households"]) * int(amount):
        why.append("pool_too_small")
    return why


def status(repo: Repo, alert_id: str) -> dict[str, Any]:
    """Per tier: eligible, or the reasons it is not. KeyError for an unknown alert."""
    alert = repo.get_alert(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    row = anchor.get(repo, alert_id)
    anchored = bool(row and row.get("state") == "sent")
    exercise = bool(row["exercise"]) if row else anchor.cap.is_exercise(alert)
    level = anchor.LEVELS.get(alert.level, 0)
    out: dict[str, Any] = {"alert_id": alert.id, "village_id": alert.village_id, "level": level,
                           "exercise": exercise, "anchored": anchored, "illustrative": ILLUSTRATIVE, "rule": None,
                           "tiers": []}
    client = _client()
    state = None
    if client is not None and anchored:
        state = client.relief_state(anchor.keccak(text=alert.village_id), anchor.alert_key(alert.id), exercise)
    if state:
        r = state["rule"]
        out["rule"] = {"min_level": r["min_level"], "amount_anticipatory_wei": str(r["amount_anticipatory_wei"]),
                       "amount_confirmed_wei": str(r["amount_confirmed_wei"]), "cooldown_hours": r["cooldown_hours"],
                       "sealed": state["sealed"], "sealed_at": state["sealed_at"]}
    for tier in TIERS:
        recorded = get_release(repo, alert.id, tier)
        entry: dict[str, Any] = {"tier": tier, "eligible": False, "why": [], "households": None, "amount_wei": None,
                                 "total_wei": None, "release": recorded}
        if client is None:
            entry["why"] = ["raahat_off"]
        elif not anchored:
            entry["why"] = ["not_anchored"]
        elif not state:
            entry["why"] = ["chain_unreachable"]
        else:
            amount = state["rule"]["amount_anticipatory_wei" if tier == 1 else "amount_confirmed_wei"]
            entry["why"] = _why(tier, alert, level, exercise, state, recorded)
            entry.update(eligible=not entry["why"], households=int(state["households"]), amount_wei=str(amount),
                         total_wei=str(int(amount) * int(state["households"])))
        out["tiers"].append(entry)
    return out


def release(repo: Repo, alert_id: str, tier: int, *, by: str) -> dict[str, Any]:
    """Send ReliefPool.release once. ReliefRefused(code) when not eligible; {"state": "failed"} when the chain
    refused or could not be reached (logged and counted; the officer may tap again)."""
    if tier not in TIERS:
        raise ReliefRefused("bad_tier")
    st = status(repo, alert_id)
    entry = st["tiers"][tier - 1]
    if not entry["eligible"]:
        raise ReliefRefused(entry["why"][0])
    alert = repo.get_alert(alert_id)
    assert alert is not None
    pk, sk = anchor.PK + alert_id, f"RELEASE#{tier}"
    claim = {"pk": pk, "sk": sk, "state": "sending", "tier": tier, "by": by, "alert_id": alert.id,
             "village_id": alert.village_id, "exercise": st["exercise"], "households": entry["households"],
             "amount_wei": entry["amount_wei"], "total_wei": entry["total_wei"], "at": clock.iso(clock.now())}
    try:
        repo._put(claim, condition=Attr("pk").not_exists() | Attr("state").eq("failed"))
    except ConflictError:
        raise ReliefRefused("already_released") from None
    client = _client()
    tx = client.release(anchor.alert_key(alert.id), tier) if client else None
    repo._update(pk, sk, {"state": "sent" if tx else "failed", "tx": tx})
    tier_name = "anticipatory" if tier == 1 else "confirmed"
    if not tx:
        repo.add_timeline(alert.id, "raahat_release", f"tier {tier} ({tier_name}) release by {by} failed on chain")
        return {**claim, "state": "failed", "tx": None}
    repo.add_timeline(alert.id, "raahat_release",
                      f"tier {tier} ({tier_name}) released by {by}: {entry['households']} households x "
                      f"{inr(entry['amount_wei'])} tINR ({ILLUSTRATIVE}); tx {tx}")
    anchor.index(repo, alert)
    _announce(alert, tier, entry, st["exercise"])
    _tell_village(repo, alert, entry)
    return {**claim, "state": "sent", "tx": tx}


def ledger(repo: Repo, village_id: str = "", limit: int = 50) -> dict[str, Any]:
    """The public ledger from the table (the indexer keeps it in step with the chain): per anchored alert, the
    anchor, the outcome and each release. Ids, levels, counts, amounts and hashes only; no officer names."""
    items = []
    for row in repo._query(anchor.LEDGER_PK, newest_first=True, limit=limit * 2):
        if village_id and row.get("village_id") != village_id:
            continue
        a = anchor.get(repo, row["alert_id"])
        if a is None:
            continue
        releases = [{k: r.get(k) for k in ("tier", "state", "tx", "households", "amount_wei", "total_wei", "at")}
                    for r in (get_release(repo, a["alert_id"], t) for t in TIERS) if r]
        items.append({"alert_id": a["alert_id"], "village_id": a.get("village_id"), "level": a.get("level"),
                      "exercise": bool(a.get("exercise")), "anchor_state": a.get("state"), "anchor_tx": a.get("tx"),
                      "anchored_at": a.get("anchored_at"), "cap_hash": a.get("cap_hash"),
                      "cap_uri": a.get("cap_uri"), "outcome_tx": a.get("outcome_tx"),
                      "delivered": a.get("delivered"), "acknowledged": a.get("acknowledged"),
                      "chain_id": a.get("chain_id"), "network": a.get("network"),
                      "explorer": chain.explorer_url(int(a.get("chain_id") or 0)), "releases": releases})
        if len(items) >= limit:
            break
    return {"items": items, "illustrative": ILLUSTRATIVE}


def _announce(alert: Alert, tier: int, entry: dict, exercise: bool) -> None:
    from Pukaar.services import events

    events.publish("/public/raahat", {"type": "raahat", "kind": "released", "alert_id": alert.id,
                                      "village_id": alert.village_id, "tier": tier,
                                      "households": int(entry["households"]), "total_wei": str(entry["total_wei"]),
                                      "exercise": bool(exercise), "at": clock.iso(clock.now())})


def relief_message(alert: Alert, amount_wei: str | int) -> str:
    # Test money on a testnet: the message must never read as a promise of real cash.
    return (f"पुकार राहत (परीक्षण, असली पैसा नहीं): {alert.village_name_hi} के हर घर के लिए ₹{inr(amount_wei)} "
            f"जारी। प्रधान या बैंक मित्र से लें। रसीद: {get_settings().web_url}/raahat?alert={alert.id}")


def _tell_village(repo: Repo, alert: Alert, entry: dict) -> None:
    """Live alerts only, to registered Telegram users of the village (never stub or voice-only). Never raises."""
    from Pukaar.delivery import telegram
    from Pukaar.policy.guard import SYSTEM, authorize

    text = relief_message(alert, entry["amount_wei"])
    for r in repo.list_recipients(alert.village_id):
        if not r.takes_telegram or r.channel == "stub":
            continue
        ctx = {"replay": bool(alert.replay), "channel": "telegram", "village_id": alert.village_id}
        if not authorize(SYSTEM, "notify_relief", "alert", alert.id, ctx, repo=repo).allowed:
            continue
        try:
            telegram.send_text(r.id, text)
        except Exception as exc:
            log(_LOG, "relief message failed", 30, alert_id=alert.id, error=f"{type(exc).__name__}: {str(exc)[:120]}")
