"""The Raahat indexer (raahat/indexer.py): contract events into the table, in block windows the public RPC allows,
from a checkpoint, in the 15-minute sweep; a pool snapshot so /raahat/pool can say "cached" when the chain is down.
Never raises: the sweep is the alert path."""

from __future__ import annotations

import pytest
from eth_abi import encode
from eth_utils import keccak, to_checksum_address
from web3.providers.base import BaseProvider

from Pukaar.raahat import chain, indexer
from test_raahat_anchor import _cfg

DONOR_A = to_checksum_address("0x" + "aa" * 20)
DONOR_B = to_checksum_address("0x" + "bb" * 20)


class FakeIndexChain:
    def __init__(self, head=1000, events=None):
        self.cfg = _cfg()
        self.head = head
        self.events = events or []
        self.windows: list[tuple[int, int]] = []
        self.down = False

    def latest_block(self):
        return None if self.down else self.head

    def read_events(self, from_block, to_block):
        if self.down:
            return None
        self.windows.append((from_block, to_block))
        return [e for e in self.events if from_block <= e["block"] <= to_block]

    def read_pool(self):
        return None if self.down else {"pool": {"balance_wei": "500"}, "block": self.head, "rule": {"sealed": True}}


def _funded(block, donor, amount, i=0):
    return {"event": "Funded", "block": block, "log_index": i, "tx": "0x" + keccak(bytes([block % 256, i])).hex(),
            "args": {"donor": donor, "amount": str(amount)}}


@pytest.fixture()
def fake(monkeypatch):
    c = FakeIndexChain(head=1000, events=[_funded(950, DONOR_A, 100), _funded(990, DONOR_B, 50, 1),
                                          _funded(995, DONOR_A, 25, 2)])
    monkeypatch.setattr(indexer, "_client", lambda: c)
    monkeypatch.setattr(indexer, "_start_block", lambda client: 900)
    return c


def test_first_run_reads_from_the_deployment_in_small_windows(repo, fake):
    out = indexer.run(repo)
    assert out["events"] == 3 and out["to_block"] == 1000 - indexer.CONFIRMATIONS
    assert all(b - a + 1 <= indexer.WINDOW for a, b in fake.windows)
    assert fake.windows[0][0] == 900
    funds = indexer.funds(repo)
    assert funds == {"donors": 2, "funded_wei": "175", "events": 3}


def test_checkpoint_means_each_event_counted_once(repo, fake):
    indexer.run(repo)
    fake.windows.clear()
    fake.head = 1010
    fake.events.append(_funded(1005, DONOR_B, 5, 3))
    out = indexer.run(repo)
    assert fake.windows[0][0] == 1000 - indexer.CONFIRMATIONS + 1
    assert out["events"] == 1 and indexer.funds(repo) == {"donors": 2, "funded_wei": "180", "events": 4}
    indexer.run(repo)  # nothing new
    assert indexer.funds(repo)["funded_wei"] == "180"


def test_catch_up_is_bounded_per_sweep(repo, fake, monkeypatch):
    monkeypatch.setattr(indexer, "_start_block", lambda client: 0)
    fake.head = 100_000
    out = indexer.run(repo)
    assert len(fake.windows) == indexer.MAX_WINDOWS
    assert out["to_block"] == indexer.MAX_WINDOWS * indexer.WINDOW - 1  # the rest next sweep


def test_chain_down_never_raises_and_keeps_the_checkpoint(repo, fake, capsys):
    indexer.run(repo)
    before = indexer.checkpoint(repo)
    fake.down = True
    out = indexer.run(repo)
    assert out["skipped"] == "chain_unreachable" and indexer.checkpoint(repo) == before
    assert '"RaahatIndexFailed": 1' in capsys.readouterr().out


def test_a_failed_window_stops_there_and_is_read_again(repo, fake):
    calls = {"n": 0}
    real = fake.read_events

    def flaky(a, b):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(a, b)

    fake.read_events = flaky
    assert indexer.run(repo)["events"] == 0 and indexer.checkpoint(repo) is None
    assert indexer.run(repo)["events"] == 3


def test_code_error_never_reaches_the_sweep(repo, monkeypatch):
    def boom():
        raise RuntimeError("bug")

    monkeypatch.setattr(indexer, "_client", boom)
    assert indexer.run(repo)["skipped"].startswith("error")


def test_pool_snapshot_is_kept_for_the_cached_fallback(repo, fake):
    indexer.run(repo)
    snap = indexer.pool_snapshot(repo)
    assert snap["pool"]["balance_wei"] == "500" and snap["indexed_at"]


def test_off_does_nothing(repo, monkeypatch):
    monkeypatch.setattr(indexer, "_client", lambda: None)
    assert indexer.run(repo) == {"skipped": "off"}


def test_pool_route_falls_back_to_the_cached_snapshot(repo, fake, monkeypatch):
    from fastapi.testclient import TestClient

    import Pukaar.api.routers.raahat as routes
    from Pukaar.main import app
    from test_raahat_chain import ScriptedProvider

    indexer.run(repo)
    monkeypatch.setattr(routes, "get_repo", lambda: repo)
    monkeypatch.setattr(chain, "load_config", lambda: _cfg())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg: ScriptedProvider(fail="*"))
    body = TestClient(app).get("/raahat/pool").json()
    assert body["reachable"] is False and body["cached"] is True
    assert body["pool"]["balance_wei"] == "500" and body["cached_at"]
    assert body["donors"] == 2 and body["funded_wei"] == "175"


# -- decoding real logs ------------------------------------------------------------------------------------
class LogsProvider(BaseProvider):
    def __init__(self, logs):
        super().__init__()
        self.logs, self.asked = logs, []

    def make_request(self, method, params):
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(31337)}
        if method == "eth_getLogs":
            self.asked.append(params[0])
            return {"jsonrpc": "2.0", "id": 1, "result": self.logs}
        raise AssertionError(method)

    def is_connected(self, show_traceback=False):
        return True


def test_read_events_decodes_funded_and_names_the_rest():
    pool = _cfg().addresses["pool"]
    alert = keccak(text="alr_1")
    logs = [
        {"address": pool, "blockNumber": hex(950), "logIndex": "0x0", "transactionHash": "0x" + "11" * 32,
         "blockHash": "0x" + "00" * 32, "transactionIndex": "0x0", "removed": False,
         "topics": ["0x" + keccak(text="Funded(address,uint256)").hex(), "0x" + "00" * 12 + "aa" * 20],
         "data": "0x" + encode(["uint256"], [175]).hex()},
        {"address": pool, "blockNumber": hex(951), "logIndex": "0x1", "transactionHash": "0x" + "22" * 32,
         "blockHash": "0x" + "00" * 32, "transactionIndex": "0x0", "removed": False,
         "topics": ["0x" + keccak(text="Released(bytes32,bytes32,uint8,uint32,uint256,bool)").hex(),
                    "0x" + alert.hex(), "0x" + keccak(text="pandoh").hex()],
         "data": "0x" + encode(["uint8", "uint32", "uint256", "bool"], [1, 30, 45000, True]).hex()},
    ]
    p = LogsProvider(logs)
    events = chain.RaahatChain(_cfg(), provider=p).read_events(900, 1000)
    assert p.asked[0]["fromBlock"] == hex(900) and p.asked[0]["toBlock"] == hex(1000)
    assert events[0] == {"event": "Funded", "block": 950, "log_index": 0, "tx": "0x" + "11" * 32,
                         "args": {"donor": DONOR_A, "amount": "175"}}
    assert events[1]["event"] == "Released" and events[1]["args"]["alert_key"] == "0x" + alert.hex()
