"""Anchoring alerts on chain (raahat/anchor.py, raahat/chain.py writes), with a scripted RPC: no network.

The rule this file guards: a chain failure never stops, delays or changes an alert. Every anchor is
attempted once per alert (a DynamoDB claim), logged, counted (RaahatTxFailed) and swallowed.
"""

from __future__ import annotations

import pytest
from eth_abi import decode
from eth_account import Account
from eth_account.typed_transactions import TypedTransaction
from eth_utils import function_signature_to_4byte_selector, keccak, to_checksum_address
from hexbytes import HexBytes
from web3.providers.base import BaseProvider

from Pukaar.raahat import anchor, chain
from Pukaar.workflow.client import decide
from test_workflow_steps import drafted_and_asked, make_alert, steps

REGISTRY = to_checksum_address("0xe7f1725e7734ce288f8367e1bb143e90bb3f0512")
TOKEN = to_checksum_address("0x5fbdb2315678afecb367f032d93f642f64180aa3")
ORACLE = to_checksum_address("0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266")
RECORD = "(bytes32,uint8,bytes32,string,uint64,bool,uint32,uint32,bytes32)"
ANCHOR_ALERT = function_signature_to_4byte_selector(f"anchorAlert(bytes32,{RECORD})")
ANCHOR_OUTCOME = function_signature_to_4byte_selector("anchorOutcome(bytes32,uint32,uint32,bytes32)")


class Chain(BaseProvider):
    """A scripted EVM endpoint that accepts transactions and remembers their calldata."""

    def __init__(self, *, chain_id: int = 31337, down: bool = False):
        super().__init__()
        self.chain_id, self.down = chain_id, down
        self.sent: list[dict] = []  # {"from", "to", "data"}
        self.nonce = 0

    def make_request(self, method, params):
        if self.down:
            raise ConnectionError("rpc down")
        result = {
            "eth_chainId": hex(self.chain_id),
            "eth_getTransactionCount": hex(self.nonce),
            "eth_estimateGas": hex(200_000),
            "eth_maxPriorityFeePerGas": hex(1_000_000),
            "eth_gasPrice": hex(2_000_000),
            "eth_accounts": [ORACLE],
            "eth_getBlockByNumber": {"number": "0x10", "baseFeePerGas": hex(1_000_000), "timestamp": "0x1",
                                     "hash": "0x" + "00" * 32, "transactions": []},
        }.get(method)
        if method == "eth_sendTransaction":
            tx = params[0]
            self.sent.append({"from": tx["from"], "to": tx["to"], "data": tx.get("data") or tx.get("input")})
            return self._tx_hash()
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0][2:])
            tx = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
            self.sent.append({"from": Account.recover_transaction(raw), "to": to_checksum_address(tx["to"]),
                              "data": "0x" + bytes(tx["data"]).hex()})
            return self._tx_hash()
        if result is None:
            raise AssertionError(f"unexpected RPC {method}")
        return {"jsonrpc": "2.0", "id": 1, "result": result}

    def _tx_hash(self):
        self.nonce += 1
        return {"jsonrpc": "2.0", "id": 1, "result": "0x" + keccak(str(len(self.sent)).encode()).hex()}

    def is_connected(self, show_traceback: bool = False) -> bool:
        return True


def _cfg(chain_id: int = 31337) -> chain.ChainConfig:
    return chain.ChainConfig(chain_id=chain_id, rpc_url="http://rpc.test", network=chain.NETWORKS.get(chain_id, "x"),
                             addresses={"test_inr": TOKEN, "pool": ORACLE, "alert_registry": REGISTRY},
                             oracle=ORACLE)


@pytest.fixture()
def fake_chain(monkeypatch):
    """Raahat configured against one scripted endpoint for the whole test."""
    endpoint = Chain()
    monkeypatch.setattr(chain, "load_config", lambda: _cfg())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, **kw: endpoint)
    return endpoint


def _decode_anchor(data: str) -> tuple:
    raw = bytes.fromhex(data[2:])
    assert raw[:4] == ANCHOR_ALERT
    return decode(["bytes32", RECORD], raw[4:])


def _deliver(repo, workflow, *, replay=False, level="warning"):
    s, a, _ = drafted_and_asked(repo, level=level, replay=replay)
    decide(repo, workflow, a.id, "approved", "officer1")
    out = s.handle({"step": "deliver", "alert_id": a.id})
    return s, a, out


# -- the alert path never depends on the chain ------------------------------------------------------
def test_chain_down_never_stops_an_alert(repo, frozen, workflow, monkeypatch, capsys):
    monkeypatch.setattr(chain, "load_config", lambda: _cfg())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, **kw: Chain(down=True))
    s, a, out = _deliver(repo, workflow)
    assert out["sent"] == 2 and out["failed"] == 0
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    assert repo.get_alert(a.id).status == "delivered"
    assert capsys.readouterr().out.count('"RaahatTxFailed": 1') == 2  # the alert at delivery, again at close
    assert anchor.get(repo, a.id)["state"] == "failed"


def test_anchor_code_crashing_never_stops_an_alert(repo, frozen, workflow, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bug in raahat")

    monkeypatch.setattr(anchor, "_anchor_alert", boom)
    monkeypatch.setattr(anchor, "_anchor_outcome", boom)
    s, a, out = _deliver(repo, workflow)
    assert out["sent"] == 2
    assert s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})["status"] == "delivered"


def test_not_configured_does_nothing(repo, frozen, workflow, monkeypatch, capsys):
    monkeypatch.setattr(chain, "load_config", lambda: None)
    s, a, out = _deliver(repo, workflow)
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    assert anchor.get(repo, a.id) is None
    assert "Raahat" not in capsys.readouterr().out


# -- what is anchored --------------------------------------------------------------------------------
def test_first_delivery_anchors_the_cap_record(repo, frozen, workflow, fake_chain):
    s, a, _ = _deliver(repo, workflow, replay=True)
    assert len(fake_chain.sent) == 1
    tx = fake_chain.sent[0]
    assert tx["to"] == REGISTRY and tx["from"] == ORACLE
    alert_id, rec = _decode_anchor(tx["data"])
    alert = repo.get_alert(a.id)
    cap_xml = anchor.cap_document(repo, alert)
    assert alert_id == keccak(text=a.id)
    assert rec[0] == keccak(text="thunag")
    assert rec[1] == 2  # warning
    assert rec[2] == keccak(cap_xml)
    assert rec[3] == f"http://localhost:8000/cap/alerts/{a.id}.xml"
    assert rec[5] is True  # a replay is an exercise
    assert rec[6:] == (0, 0, b"\x00" * 32)
    row = anchor.get(repo, a.id)
    assert row["state"] == "sent" and row["tx"].startswith("0x") and row["cap_hash"] == "0x" + keccak(cap_xml).hex()
    assert row["exercise"] is True and row["registry"] == REGISTRY and row["chain_id"] == 31337


def test_cap_hash_matches_what_the_feed_serves_after_close(repo, frozen, workflow, fake_chain, monkeypatch):
    """Re-verify only works if the CAP XML anchored at delivery is byte-for-byte what /cap/alerts/{id}.xml
    serves later, after the alert has closed."""
    from fastapi.testclient import TestClient

    import Pukaar.api.routers.public as public
    from Pukaar.main import app

    s, a, _ = _deliver(repo, workflow)
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    monkeypatch.setattr(public, "get_repo", lambda: repo)
    body = TestClient(app).get(f"/cap/alerts/{a.id}.xml").content
    assert "0x" + keccak(body).hex() == anchor.get(repo, a.id)["cap_hash"]


def test_live_alert_is_not_an_exercise_and_a_drill_is(repo, frozen, workflow, fake_chain):
    _deliver(repo, workflow, replay=False)
    assert _decode_anchor(fake_chain.sent[0]["data"])[1][5] is False

    drill = make_alert(repo, "watch", village="gohar")
    repo.update_alert(drill.id, decision_trace={"drill": True, "rules_fired": ["drill"]}, status="approved",
                      approved=True)
    anchor.on_delivered(repo, drill.id)
    assert _decode_anchor(fake_chain.sent[1]["data"])[1][5] is True


def test_anchor_is_sent_once_per_alert(repo, frozen, workflow, fake_chain):
    s, a, _ = _deliver(repo, workflow)
    anchor.on_delivered(repo, a.id)  # a re-run of the step, a recall, a second Map batch
    anchor.on_delivered(repo, a.id)
    assert len(fake_chain.sent) == 1


def test_unpublished_alert_is_never_anchored(repo, frozen, fake_chain):
    a = make_alert(repo, "warning")  # still drafting: never went out
    anchor.on_delivered(repo, a.id)
    anchor.on_close(repo, a.id)
    assert fake_chain.sent == [] and anchor.get(repo, a.id) is None


def test_close_anchors_the_outcome_with_the_after_action_hash(repo, frozen, workflow, fake_chain):
    from Pukaar.services import after_action

    s, a, _ = _deliver(repo, workflow)
    repo.update_alert(a.id, acknowledged_count=1)
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    assert len(fake_chain.sent) == 2
    raw = bytes.fromhex(fake_chain.sent[1]["data"][2:])
    assert raw[:4] == ANCHOR_OUTCOME
    alert_id, delivered, acked, report_hash = decode(["bytes32", "uint32", "uint32", "bytes32"], raw[4:])
    alert = repo.get_alert(a.id)
    assert alert_id == keccak(text=a.id)
    assert (delivered, acked) == (alert.delivered_count, alert.acknowledged_count) == (2, 1)
    assert report_hash == keccak(after_action.load_stored(a.id).encode("utf-8"))
    row = anchor.get(repo, a.id)
    assert row["outcome_state"] == "sent" and row["outcome_tx"].startswith("0x")
    anchor.on_close(repo, a.id)  # closing twice never anchors twice
    assert len(fake_chain.sent) == 2


def test_close_retries_a_failed_alert_anchor_first(repo, frozen, workflow, monkeypatch):
    endpoint = Chain(down=True)
    monkeypatch.setattr(chain, "load_config", lambda: _cfg())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, **kw: endpoint)
    s, a, _ = _deliver(repo, workflow)
    assert anchor.get(repo, a.id)["state"] == "failed"
    anchor.on_delivered(repo, a.id)  # a later batch does not retry: only close does, once
    endpoint.down = False
    s.handle({"step": "close", "alert_id": a.id, "outcome": "delivered"})
    sels = [bytes.fromhex(t["data"][2:10]) for t in endpoint.sent]
    assert sels == [ANCHOR_ALERT, ANCHOR_OUTCOME]
    assert anchor.get(repo, a.id)["state"] == "sent"


def test_no_registry_configured_skips_quietly(repo, frozen, workflow, monkeypatch):
    cfg = _cfg()
    cfg = chain.ChainConfig(**{**cfg.__dict__, "addresses": {"test_inr": TOKEN, "pool": ORACLE}})
    endpoint = Chain()
    monkeypatch.setattr(chain, "load_config", lambda: cfg)
    monkeypatch.setattr(chain, "_provider_for", lambda c, **kw: endpoint)
    _deliver(repo, workflow)
    assert endpoint.sent == []


# -- signing -----------------------------------------------------------------------------------------
def test_a_configured_key_signs_locally(repo, frozen, workflow, monkeypatch):
    acct = Account.create()
    endpoint = Chain(chain_id=84532)
    monkeypatch.setattr(chain, "load_config", lambda: _cfg(84532))
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, **kw: endpoint)
    monkeypatch.setenv("RAAHAT_SIGNER_KEY", acct.key.hex())
    _deliver(repo, workflow)
    assert endpoint.sent[0]["from"] == acct.address
    assert endpoint.sent[0]["to"] == REGISTRY


def test_a_public_chain_without_a_key_fails_and_is_counted(repo, frozen, workflow, monkeypatch, capsys):
    """Only anvil's unlocked accounts may be used without a key; a testnet never is."""
    monkeypatch.delenv("RAAHAT_SIGNER_KEY", raising=False)
    endpoint = Chain(chain_id=84532)
    monkeypatch.setattr(chain, "load_config", lambda: _cfg(84532))
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, **kw: endpoint)
    _, a, out = _deliver(repo, workflow)
    assert out["sent"] == 2 and endpoint.sent == []
    assert anchor.get(repo, a.id)["state"] == "failed"
    assert '"RaahatTxFailed": 1' in capsys.readouterr().out


def test_signer_key_comes_from_its_own_ssm_path_on_aws(monkeypatch):
    calls = []

    class SSM:
        def get_parameter(self, Name, WithDecryption):
            calls.append((Name, WithDecryption))
            return {"Parameter": {"Value": "0x" + "11" * 32}}

    monkeypatch.delenv("RAAHAT_SIGNER_KEY", raising=False)
    monkeypatch.setattr(chain, "_ssm_client", lambda: SSM())
    monkeypatch.setattr(chain, "_aws_mode", lambda: True)
    monkeypatch.setenv("PUKAAR_STAGE", "dev")
    chain._KEY_CACHE.clear()
    assert chain.signer_key() == "0x" + "11" * 32
    assert calls == [("/pukaar-raahat/dev/signer_key", True)]


def test_public_anchor_view_has_no_personal_data(repo, frozen, workflow, fake_chain):
    s, a, _ = _deliver(repo, workflow)
    view = anchor.public_view(repo, a.id)
    assert set(view) == {"alert_id", "alert_key", "village_id", "level", "exercise", "cap_hash", "cap_uri",
                         "registry", "chain_id", "network", "explorer", "tx", "state", "anchored_at",
                         "outcome_tx", "outcome_state", "delivered", "acknowledged", "after_action_hash"}
    assert view["level"] == 2 and view["village_id"] == "thunag"


# -- review fix: the anchor never sits between the alert and anyone it has not reached yet ----------------------
def test_anchor_waits_until_every_batch_has_been_sent(repo, frozen, workflow, fake_chain, monkeypatch):
    """With more than one batch, deliver hands the rest to the Map: nothing may be sent to the chain before the
    last batch has gone out (a slow RPC must never hold up a warning)."""
    from Pukaar.core import config
    from Pukaar.workflow.steps import drive_delivery

    monkeypatch.setenv("PUKAAR_DELIVERY_BATCH_SIZE", "1")
    config.get_settings.cache_clear()
    try:
        s, a, _ = drafted_and_asked(repo)
        decide(repo, workflow, a.id, "approved", "officer1")
        first = s.handle({"step": "deliver", "alert_id": a.id})
        assert first["more"] is True and fake_chain.sent == []  # batch 1 still to go: no anchor yet
        done = drive_delivery(s.handle, first, sleep=lambda _: None)
        assert done["sent"] == 2 and len(fake_chain.sent) == 1  # anchored once, after the round
    finally:
        config.get_settings.cache_clear()


def test_rpc_client_never_retries_on_the_alert_path_and_retries_a_little_elsewhere():
    """web3's HTTPProvider retries each call 5 times by default; on the alert path that turns a sick RPC into
    minutes, so the anchor's client gets one try per call and a short timeout. An officer's release or a page read
    is not on the alert path: a flaky or rate-limiting public RPC gets three more tries there, with backoff."""
    alert_path = chain._provider_for(_cfg(), alert_path=True)
    assert alert_path.exception_retry_configuration is None
    assert alert_path.get_request_kwargs()["timeout"] <= 3
    other = chain._provider_for(_cfg())
    assert other.exception_retry_configuration.retries == 3


def test_the_anchor_uses_the_alert_path_client(monkeypatch):
    seen = []
    monkeypatch.setattr(chain, "load_config", lambda: _cfg())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg, alert_path=False: seen.append(alert_path) or Chain())
    anchor._client()
    assert seen == [True]
