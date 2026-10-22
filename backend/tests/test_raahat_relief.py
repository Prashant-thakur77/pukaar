"""Relief release (raahat/relief.py, POST /raahat/alerts/{id}/release): code decides eligibility, an officer
releases, the ReliefPool contract enforces the sealed rule. A fake chain client stands in for the RPC here;
the release transaction's calldata is checked against a scripted RPC in test_release_calldata."""

from __future__ import annotations

import pytest
from eth_abi import decode
from eth_utils import function_signature_to_4byte_selector, keccak

from Pukaar.policy.guard import Principal
from Pukaar.raahat import anchor, chain, relief
from Pukaar.services import events
from test_raahat_anchor import Chain, _cfg
from test_workflow_steps import make_alert

OFFICER = Principal("officer1", "officer")
WEI = 10**18


class FakeChain:
    """Duck-types the RaahatChain calls relief.py makes."""

    def __init__(self, **over):
        self.cfg = _cfg()
        self.state = {
            "sealed": True, "sealed_at": 1_780_000_000, "allow_exercise": True,
            "rule": {"min_level": 2, "amount_anticipatory_wei": 1500 * WEI, "amount_confirmed_wei": 4000 * WEI,
                     "cooldown_hours": 72},
            "households": 42, "agent": "0x" + "ab" * 20, "balance_wei": 500_000 * WEI,
            "released": {1: False, 2: False}, "last_anticipatory": 0, "now": 1_790_000_000, "confirmed": False,
        }
        self.state.update(over)
        self.sent: list[tuple[str, int]] = []
        self.fail = False
        self.outcome = "mined"  # what confirm() says: mined, reverted or pending

    def confirm(self, tx: str) -> str:
        return self.outcome

    def relief_state(self, village_key: bytes, alert_key: bytes, exercise: bool) -> dict | None:
        return dict(self.state)

    def release(self, alert_key: bytes, tier: int) -> str | None:
        if self.fail:
            return None
        self.sent.append(("0x" + alert_key.hex(), tier))
        return "0x" + keccak(alert_key + bytes([tier])).hex()


def _anchored(repo, *, level="warning", replay=True, village="sujanpur"):
    a = make_alert(repo, level, replay=replay, village=village)
    repo.update_alert(a.id, status="delivered", approved=True, delivered_count=2)
    repo._put({"pk": anchor.PK + a.id, "sk": anchor.SK, "state": "sent", "alert_id": a.id, "village_id": village,
               "level": anchor.LEVELS[level], "exercise": replay, "tx": "0xabc", "chain_id": 31337,
               "network": "anvil", "registry": "0x" + "11" * 20, "alert_key": "0x" + anchor.alert_key(a.id).hex()})
    return repo.get_alert(a.id)


@pytest.fixture()
def fake(monkeypatch, repo):
    from Pukaar.handlers import worker

    monkeypatch.setattr(worker, "get_repo", lambda: repo)
    monkeypatch.setattr(relief, "NOTIFY_INTERVAL_SECONDS", 0)
    c = FakeChain()
    monkeypatch.setattr(relief, "_client", lambda: c)
    # The village is told by the worker (async invoke on AWS, a thread locally); here inline, so tests see it.
    monkeypatch.setattr(worker, "dispatch", lambda event: worker.run_task(event))
    return c


# -- eligibility -----------------------------------------------------------------------------------------
def test_warning_alert_is_eligible_for_the_anticipatory_tier(repo, frozen, fake):
    a = _anchored(repo)
    st = relief.status(repo, a.id)
    t1 = st["tiers"][0]
    assert t1["tier"] == 1 and t1["eligible"] is True and t1["why"] == []
    assert (t1["households"], t1["amount_wei"], t1["total_wei"]) == (42, str(1500 * WEI), str(42 * 1500 * WEI))
    assert st["illustrative"] == "illustrative, SDRF norms to be mapped with DDMA"
    assert st["tiers"][1]["eligible"] is False and "not_confirmed" in st["tiers"][1]["why"]


@pytest.mark.parametrize("over, code", [
    ({"sealed": False}, "rules_not_sealed"),
    ({"households": 0}, "no_households"),
    ({"agent": None}, "no_agent"),
    ({"balance_wei": 10 * WEI}, "pool_too_small"),
    ({"released": {1: True, 2: False}}, "already_released"),
    ({"last_anticipatory": 1_790_000_000 - 3600}, "cooldown"),
    ({"allow_exercise": False}, "exercise_not_allowed"),
])
def test_each_refusal_has_a_reason_code(repo, frozen, monkeypatch, over, code):
    c = FakeChain(**over)
    monkeypatch.setattr(relief, "_client", lambda: c)
    a = _anchored(repo)
    t1 = relief.status(repo, a.id)["tiers"][0]
    assert t1["eligible"] is False and code in t1["why"]


def test_watch_level_is_below_the_rule(repo, frozen, fake):
    a = _anchored(repo, level="watch")
    assert "level_below_rule" in relief.status(repo, a.id)["tiers"][0]["why"]


def test_unanchored_alert_is_not_eligible(repo, frozen, fake):
    a = make_alert(repo, "warning", replay=True, village="sujanpur")
    st = relief.status(repo, a.id)
    assert st["anchored"] is False and "not_anchored" in st["tiers"][0]["why"]


def test_chain_unreachable_is_a_reason_not_a_crash(repo, frozen, monkeypatch):
    c = FakeChain()
    c.relief_state = lambda *a, **k: None
    monkeypatch.setattr(relief, "_client", lambda: c)
    a = _anchored(repo)
    assert "chain_unreachable" in relief.status(repo, a.id)["tiers"][0]["why"]


def test_raahat_off_means_no_relief(repo, frozen, monkeypatch):
    monkeypatch.setattr(relief, "_client", lambda: None)
    a = _anchored(repo)
    assert relief.status(repo, a.id)["tiers"][0]["why"] == ["raahat_off"]


# -- release -----------------------------------------------------------------------------------------------
def test_release_sends_once_records_and_announces(repo, frozen, fake, monkeypatch):
    published = []
    monkeypatch.setattr(events, "publish", lambda channel, event: published.append((channel, event)) or True)
    a = _anchored(repo)
    out = relief.release(repo, a.id, 1, by="officer1")
    assert out["state"] == "sent" and out["tx"].startswith("0x")
    assert fake.sent == [("0x" + anchor.alert_key(a.id).hex(), 1)]
    row = relief.get_release(repo, a.id, 1)
    assert (row["by"], row["households"], row["total_wei"], row["exercise"]) == ("officer1", 42, str(42 * 1500 * WEI),
                                                                                 True)
    with pytest.raises(relief.ReliefRefused) as e:
        relief.release(repo, a.id, 1, by="officer1")
    assert e.value.code == "already_released"
    assert len(fake.sent) == 1
    # AppSync: ids, levels and amounts only
    ch, ev = published[-1]
    assert ch == "/public/raahat"
    assert set(ev) == {"type", "kind", "alert_id", "village_id", "tier", "households", "total_wei", "exercise", "at"}
    assert ev["kind"] == "released" and ev["total_wei"] == str(42 * 1500 * WEI)
    assert any(t.step == "raahat_release" for t in repo.list_timeline(a.id))


def test_release_refused_when_not_eligible_sends_nothing(repo, frozen, monkeypatch):
    c = FakeChain(households=0)
    monkeypatch.setattr(relief, "_client", lambda: c)
    a = _anchored(repo)
    with pytest.raises(relief.ReliefRefused) as e:
        relief.release(repo, a.id, 1, by="officer1")
    assert e.value.code == "no_households" and c.sent == []
    assert relief.get_release(repo, a.id, 1) is None


def test_failed_transaction_can_be_released_again(repo, frozen, fake):
    a = _anchored(repo)
    fake.fail = True
    assert relief.release(repo, a.id, 1, by="officer1")["state"] == "failed"
    fake.fail = False
    assert relief.release(repo, a.id, 1, by="officer2")["state"] == "sent"
    assert relief.get_release(repo, a.id, 1)["by"] == "officer2"


def test_live_release_tells_registered_telegram_villagers_and_says_it_is_test_money(repo, frozen, fake, monkeypatch):
    from Pukaar.delivery import telegram
    from Pukaar.store.models import Recipient

    sent = []
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: sent.append((chat, text)))
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=False)
    relief.release(repo, a.id, 1, by="officer1")
    assert [c for c, _ in sent] == ["555001"]  # stub recipients are never messaged
    text = sent[0][1]
    assert "₹1,500" in text and "सुजानपुर" in text and "/raahat?alert=" + a.id in text
    assert "परीक्षण" in text  # test money on a testnet: never a promise of real cash
    assert "Asha" not in text


def test_replay_release_never_messages_a_real_phone(repo, frozen, fake, monkeypatch):
    from Pukaar.delivery import telegram
    from Pukaar.store.models import Recipient

    sent = []
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: sent.append(chat))
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=True)
    relief.release(repo, a.id, 1, by="officer1")
    assert sent == []


def test_telegram_failure_never_undoes_a_release(repo, frozen, fake, monkeypatch):
    from Pukaar.delivery import telegram
    from Pukaar.store.models import Recipient

    def boom(*_a):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram, "send_text", boom)
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=False)
    assert relief.release(repo, a.id, 1, by="officer1")["state"] == "sent"


# -- the chain call ---------------------------------------------------------------------------------------
def test_release_calldata(monkeypatch):
    endpoint = Chain()
    cfg = chain.ChainConfig(**{**_cfg().__dict__, "pool_is_contract": True})
    client = chain.RaahatChain(cfg, provider=endpoint)
    key = keccak(text="alr_x")
    assert client.release(key, 1).startswith("0x")
    raw = bytes.fromhex(endpoint.sent[0]["data"][2:])
    assert raw[:4] == function_signature_to_4byte_selector("release(bytes32,uint8)")
    assert decode(["bytes32", "uint8"], raw[4:]) == (key, 1)
    assert endpoint.sent[0]["to"] == cfg.addresses["pool"]


def test_release_refuses_a_pool_that_is_not_a_contract(capsys):
    client = chain.RaahatChain(_cfg(), provider=Chain())  # pool_is_contract False: the deployer's address
    assert client.release(keccak(text="alr_x"), 1) is None
    assert '"RaahatTxFailed": 1' in capsys.readouterr().out


# -- the API ----------------------------------------------------------------------------------------------
@pytest.fixture()
def api(monkeypatch, repo):
    from fastapi.testclient import TestClient

    import Pukaar.api.auth as auth
    import Pukaar.api.routers.raahat as routes
    from Pukaar.main import app

    monkeypatch.setattr(routes, "get_repo", lambda: repo)
    monkeypatch.setattr(auth, "get_repo", lambda: repo)
    return TestClient(app), auth


def _bearer(auth, user):
    return {"authorization": f"Bearer {auth.dev_token(user)}"}


def test_officer_releases_through_the_api(api, repo, frozen, fake):
    client, auth = api
    a = _anchored(repo)
    r = client.post(f"/raahat/alerts/{a.id}/release", json={"tier": 1}, headers=_bearer(auth, "officer1"))
    assert r.status_code == 200 and r.json()["state"] == "sent"
    again = client.post(f"/raahat/alerts/{a.id}/release", json={"tier": 1}, headers=_bearer(auth, "officer1"))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_released"


def test_pradhan_and_anonymous_cannot_release(api, repo, frozen, fake):
    client, auth = api
    a = _anchored(repo)
    assert client.post(f"/raahat/alerts/{a.id}/release", json={"tier": 1}).status_code == 401
    r = client.post(f"/raahat/alerts/{a.id}/release", json={"tier": 1}, headers=_bearer(auth, "pradhan_thunag"))
    assert r.status_code == 403
    assert fake.sent == []


def test_judge_releases_only_for_a_replay(api, repo, frozen, fake):
    client, auth = api
    live = _anchored(repo, replay=False)
    replay = _anchored(repo, replay=True, village="gohar")
    assert client.post(f"/raahat/alerts/{live.id}/release", json={"tier": 1},
                       headers=_bearer(auth, "judge")).status_code == 403
    assert client.post(f"/raahat/alerts/{replay.id}/release", json={"tier": 1},
                       headers=_bearer(auth, "judge")).status_code == 200


def test_officer_sees_eligibility(api, repo, frozen, fake):
    client, auth = api
    a = _anchored(repo)
    r = client.get(f"/raahat/alerts/{a.id}/relief", headers=_bearer(auth, "officer1"))
    assert r.status_code == 200 and r.json()["tiers"][0]["eligible"] is True
    assert client.get(f"/raahat/alerts/{a.id}/relief").status_code == 401


# -- the public ledger -------------------------------------------------------------------------------------
def test_ledger_lists_anchored_alerts_with_releases_and_nothing_personal(api, repo, frozen, fake, monkeypatch):
    client, auth = api
    from Pukaar.store.models import Recipient

    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha Devi", channel="telegram"))
    a = _anchored(repo)
    anchor.index(repo, a)
    relief.release(repo, a.id, 1, by="officer1")
    body = client.get("/raahat/ledger").json()
    item = next(i for i in body["items"] if i["alert_id"] == a.id)
    assert item["village_id"] == "sujanpur" and item["exercise"] is True and item["anchor_tx"] == "0xabc"
    assert [(r["tier"], r["state"], r["total_wei"]) for r in item["releases"]] == [(1, "sent", str(42 * 1500 * WEI))]
    assert body["illustrative"] == relief.ILLUSTRATIVE
    text = client.get("/raahat/ledger").text
    assert "Asha" not in text and "555001" not in text and "officer1" not in text
    assert client.get("/raahat/ledger?village_id=gohar").json()["items"] == []


def test_drill_release_never_messages_a_real_phone(repo, frozen, fake, monkeypatch):
    """A drill is not a replay (replay=False) but it is an exercise: relief for it is never announced to villagers."""
    from Pukaar.delivery import telegram
    from Pukaar.store.models import Recipient

    sent = []
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: sent.append(chat))
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=False)
    repo.update_alert(a.id, decision_trace={"drill": True, "rules_fired": ["drill"]})
    assert relief.release(repo, a.id, 1, by="officer1")["state"] == "sent"
    assert sent == []



# -- review fix: "sent" means mined; a revert or a still-pending transaction is never announced ------------------
@pytest.mark.parametrize("outcome, state", [("reverted", "failed"), ("pending", "pending")])
def test_release_is_only_sent_once_mined(repo, frozen, fake, monkeypatch, outcome, state):
    from Pukaar.delivery import telegram
    from Pukaar.store.models import Recipient

    told, published = [], []
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: told.append(chat))
    monkeypatch.setattr(events, "publish", lambda ch, ev: published.append(ev) or True)
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=False)
    fake.outcome = outcome
    out = relief.release(repo, a.id, 1, by="officer1")
    assert out["state"] == state and relief.get_release(repo, a.id, 1)["state"] == state
    assert told == [] and published == []
    if outcome == "reverted":  # the chain refused it: the officer may tap again
        fake.outcome = "mined"
        assert relief.release(repo, a.id, 1, by="officer1")["state"] == "sent"


def test_send_retries_a_nonce_collision_with_a_fresh_nonce():
    """Two Lambdas signing with one key can race for a nonce: the loser is sent again, not lost."""
    endpoint = Chain()
    calls = {"n": 0}
    real = endpoint.make_request

    def racy(method, params):
        if method == "eth_sendTransaction":
            calls["n"] += 1
            if calls["n"] == 1:
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nonce too low"}}
        return real(method, params)

    endpoint.make_request = racy
    cfg = chain.ChainConfig(**{**_cfg().__dict__, "pool_is_contract": True})
    assert chain.RaahatChain(cfg, provider=endpoint).release(keccak(text="alr_n"), 1).startswith("0x")
    assert calls["n"] == 2 and len(endpoint.sent) == 1


def test_confirm_reads_the_receipt_status():
    class R(Chain):
        def __init__(self, status):
            super().__init__()
            self.status = status

        def make_request(self, method, params):
            if method == "eth_getTransactionReceipt":
                if self.status is None:
                    return {"jsonrpc": "2.0", "id": 1, "result": None}
                return {"jsonrpc": "2.0", "id": 1, "result": {
                    "status": hex(self.status), "blockNumber": "0x10", "transactionHash": "0x" + "ab" * 32,
                    "blockHash": "0x" + "00" * 32, "transactionIndex": "0x0", "logs": [], "gasUsed": "0x1",
                    "cumulativeGasUsed": "0x1", "from": "0x" + "00" * 20, "to": "0x" + "00" * 20,
                    "contractAddress": None, "logsBloom": "0x" + "00" * 256, "type": "0x2",
                    "effectiveGasPrice": "0x1"}}
            return super().make_request(method, params)

    tx = "0x" + "ab" * 32
    assert chain.RaahatChain(_cfg(), provider=R(1)).confirm(tx, timeout=1) == "mined"
    assert chain.RaahatChain(_cfg(), provider=R(0)).confirm(tx, timeout=1) == "reverted"
    assert chain.RaahatChain(_cfg(), provider=R(None)).confirm(tx, timeout=1) == "pending"



def test_relief_message_goes_through_the_worker_once(repo, frozen, fake, monkeypatch):
    """The API Lambda never sends to villagers itself (Telegram's quota is shared with alert delivery): it hands a
    raahat_notify task to the worker, which tells each person once even if the task runs twice."""
    from Pukaar.delivery import telegram
    from Pukaar.handlers import worker
    from Pukaar.store.models import Recipient

    tasks, sent = [], []
    monkeypatch.setattr(worker, "dispatch", lambda event: tasks.append(event))
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: sent.append(chat))
    repo.put_recipient(Recipient(id="555001", village_id="sujanpur", name="Asha", channel="telegram"))
    a = _anchored(repo, replay=False)
    relief.release(repo, a.id, 1, by="officer1")
    assert sent == [] and tasks == [{"task": "raahat_notify", "alert_id": a.id, "tier": 1}]
    worker.run_task(tasks[0])
    worker.run_task(tasks[0])  # a duplicate delivery of the task
    assert sent == ["555001"]


def test_clear_exercise_cooldown_calldata():
    endpoint = Chain()
    cfg = chain.ChainConfig(**{**_cfg().__dict__, "pool_is_contract": True})
    assert chain.RaahatChain(cfg, provider=endpoint).clear_exercise_cooldown(keccak(text="pandoh")).startswith("0x")
    raw = bytes.fromhex(endpoint.sent[0]["data"][2:])
    assert raw[:4] == function_signature_to_4byte_selector("clearExerciseCooldown(bytes32)")
    assert decode(["bytes32"], raw[4:]) == (keccak(text="pandoh"),)
