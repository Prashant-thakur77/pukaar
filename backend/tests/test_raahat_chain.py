"""Raahat chain client (raahat/chain.py) against a scripted web3 provider: no network, no anvil.

A read that fails (RPC down, wrong chain, bad answer) returns None and is logged and counted; it never
raises. Settings come from RAAHAT_* env or, in local mode, the anvil deployment file.
"""

from __future__ import annotations

import json

import pytest
from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector, to_checksum_address
from Pukaar.raahat import chain
from web3.providers.base import BaseProvider

TOKEN = to_checksum_address("0x5fbdb2315678afecb367f032d93f642f64180aa3")
POOL = to_checksum_address("0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266")


def _sel(sig: str) -> str:
    return "0x" + function_signature_to_4byte_selector(sig).hex()


class ScriptedProvider(BaseProvider):
    """Answers the JSON-RPC calls the client makes; anything else is a test failure."""

    def __init__(self, *, chain_id: int = 31337, balance: int = 0, fail: str | None = None):
        super().__init__()
        self.chain_id, self.balance, self.fail = chain_id, balance, fail
        self.calls: list[tuple[str, list]] = []

    def make_request(self, method, params):
        self.calls.append((method, params))
        if self.fail in {method, "*"}:
            raise ConnectionError("rpc down")
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(self.chain_id)}
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(1234)}
        if method == "eth_call":
            tx = params[0]
            data = tx.get("data") or tx.get("input")
            assert tx["to"].lower() == TOKEN.lower(), tx
            if data.startswith(_sel("symbol()")):
                out = encode(["string"], ["tINR"])
            elif data.startswith(_sel("decimals()")):
                out = encode(["uint8"], [18])
            elif data.startswith(_sel("balanceOf(address)")):
                (who,) = decode(["address"], bytes.fromhex(data[10:]))
                assert who.lower() == POOL.lower()
                out = encode(["uint256"], [self.balance])
            else:
                raise AssertionError(f"unexpected call {data[:10]}")
            return {"jsonrpc": "2.0", "id": 1, "result": "0x" + out.hex()}
        raise AssertionError(f"unexpected RPC {method}")

    def is_connected(self, show_traceback: bool = False) -> bool:
        return True


def _config(**over) -> chain.ChainConfig:
    base = dict(chain_id=31337, rpc_url="http://127.0.0.1:8545", network="anvil",
                addresses={"test_inr": TOKEN, "pool": POOL}, pool_is_contract=False)
    return chain.ChainConfig(**{**base, **over})


def test_read_pool_returns_balance_as_exact_wei_string():
    provider = ScriptedProvider(balance=500_000 * 10**18)
    pool = chain.RaahatChain(_config(), provider=provider).read_pool()
    assert pool == {
        "chain_id": 31337, "network": "anvil", "explorer": None, "block": 1234,
        "token": {"address": TOKEN, "symbol": "tINR", "decimals": 18},
        "pool": {"address": POOL, "is_contract": False, "balance_wei": str(500_000 * 10**18)},
        "rule": None,
    }


def test_rpc_down_returns_none_logs_and_counts(capsys, monkeypatch):
    logged = []
    monkeypatch.setattr(chain, "log", lambda _l, msg, sev=20, **f: logged.append((msg, sev, f)))
    pool = chain.RaahatChain(_config(), provider=ScriptedProvider(fail="*")).read_pool()
    assert pool is None
    assert '"RaahatReadFailed": 1' in capsys.readouterr().out
    assert logged == [("raahat read failed", 40, {"what": "read_pool", "network": "anvil",
                                                  "error": "ConnectionError: rpc down"})]


def test_wrong_chain_is_refused_not_read():
    """An RPC on another chain must never be read as our pool (a misconfigured URL)."""
    provider = ScriptedProvider(chain_id=1)
    assert chain.RaahatChain(_config(), provider=provider).read_pool() is None
    assert [m for m, _ in provider.calls] == ["eth_chainId"]


def test_explorer_links_per_chain():
    assert chain.explorer_url(84532) == "https://sepolia.basescan.org"
    assert chain.explorer_url(421614) == "https://sepolia.arbiscan.io"
    assert chain.explorer_url(80002) == "https://amoy.polygonscan.com"
    assert chain.explorer_url(31337) is None


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("RAAHAT_RPC_URL", "https://sepolia.base.org")
    monkeypatch.setenv("RAAHAT_CHAIN_ID", "84532")
    monkeypatch.setenv("RAAHAT_TEST_INR", TOKEN.lower())
    monkeypatch.setenv("RAAHAT_POOL", POOL.lower())
    cfg = chain.load_config()
    assert cfg is not None
    assert (cfg.chain_id, cfg.rpc_url, cfg.network) == (84532, "https://sepolia.base.org", "base-sepolia")
    assert cfg.public_rpc_url == "https://sepolia.base.org"
    assert cfg.addresses == {"test_inr": TOKEN, "pool": POOL}  # checksummed


def test_config_from_deployment_file_in_local_mode(monkeypatch, tmp_path):
    for k in ("RAAHAT_RPC_URL", "RAAHAT_CHAIN_ID", "RAAHAT_TEST_INR", "RAAHAT_POOL"):
        monkeypatch.delenv(k, raising=False)
    dep = tmp_path / "anvil.json"
    dep.write_text(json.dumps({"chain_id": 31337, "network": "anvil", "test_inr": TOKEN.lower(),
                               "pool": POOL.lower(), "pool_is_contract": False}))
    monkeypatch.setenv("RAAHAT_DEPLOYMENTS", str(dep))
    cfg = chain.load_config()
    assert cfg is not None
    assert (cfg.chain_id, cfg.rpc_url) == (31337, "http://127.0.0.1:8545")
    assert cfg.addresses == {"test_inr": TOKEN, "pool": POOL}


def test_not_configured_is_none(monkeypatch, tmp_path):
    for k in ("RAAHAT_RPC_URL", "RAAHAT_CHAIN_ID", "RAAHAT_TEST_INR", "RAAHAT_POOL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RAAHAT_DEPLOYMENTS", str(tmp_path / "missing.json"))
    assert chain.load_config() is None


def test_bad_address_in_env_is_not_configured(monkeypatch):
    monkeypatch.setenv("RAAHAT_RPC_URL", "https://sepolia.base.org")
    monkeypatch.setenv("RAAHAT_CHAIN_ID", "84532")
    monkeypatch.setenv("RAAHAT_TEST_INR", "0xnot-an-address")
    monkeypatch.setenv("RAAHAT_POOL", POOL)
    assert chain.load_config() is None


@pytest.fixture()
def api_client():
    from fastapi.testclient import TestClient
    from Pukaar.main import app

    return TestClient(app)


def test_pool_route_not_configured(api_client, monkeypatch, tmp_path):
    monkeypatch.setattr(chain, "load_config", lambda: None)
    r = api_client.get("/raahat/pool")
    assert r.status_code == 200
    assert r.json() == {"configured": False}


def test_pool_route_reports_unreachable_with_addresses(api_client, monkeypatch):
    """The page still gets the addresses, so the browser can try the chain itself and say what failed."""
    monkeypatch.setattr(chain, "load_config", lambda: _config())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg: ScriptedProvider(fail="*"))
    body = api_client.get("/raahat/pool").json()
    assert body["configured"] is True and body["reachable"] is False
    assert body["chain_id"] == 31337
    assert body["addresses"] == {"test_inr": TOKEN, "pool": POOL}
    assert body["pool_is_contract"] is False


def test_pool_route_never_exposes_the_server_rpc_url(api_client, monkeypatch):
    """RAAHAT_RPC_URL may carry a provider key: the page gets the chain's public endpoint instead."""
    cfg = _config(chain_id=84532, network="base-sepolia", rpc_url="https://base-sepolia.example/v2/SECRETKEY",
                  public_rpc_url="https://sepolia.base.org")
    monkeypatch.setattr(chain, "load_config", lambda: cfg)
    monkeypatch.setattr(chain, "_provider_for", lambda c: ScriptedProvider(chain_id=84532, fail="eth_call"))
    r = api_client.get("/raahat/pool")
    assert "SECRETKEY" not in r.text
    assert r.json()["public_rpc_url"] == "https://sepolia.base.org"


def test_pool_route_reads_balance(api_client, monkeypatch):
    monkeypatch.setattr(chain, "load_config", lambda: _config())
    monkeypatch.setattr(chain, "_provider_for", lambda cfg: ScriptedProvider(balance=7 * 10**18))
    body = api_client.get("/raahat/pool").json()
    assert body["reachable"] is True
    assert body["pool"]["balance_wei"] == str(7 * 10**18)
    assert body["token"]["symbol"] == "tINR"


def test_deployments_off_switches_raahat_off_in_local_mode(monkeypatch):
    for k in ("RAAHAT_RPC_URL", "RAAHAT_CHAIN_ID", "RAAHAT_TEST_INR", "RAAHAT_POOL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RAAHAT_DEPLOYMENTS", "off")
    assert chain.load_config() is None


def test_alert_anchor_route(api_client, monkeypatch):
    from Pukaar.raahat import anchor

    monkeypatch.setattr(anchor, "public_view", lambda repo, alert_id: {"alert_id": alert_id, "tx": "0xabc"}
                        if alert_id == "alr_1" else None)
    monkeypatch.setattr(chain, "load_config", lambda: None)
    assert api_client.get("/raahat/alerts/alr_1").json() == {"alert_id": "alr_1", "tx": "0xabc", "public_rpc_url": None}
    assert api_client.get("/raahat/alerts/alr_none").status_code == 404


def test_a_deployed_stack_never_points_at_a_local_anvil(monkeypatch):
    """Anvil (31337) is for local mode only: a stack given anvil addresses runs with Raahat off."""
    monkeypatch.setattr(chain, "_aws_mode", lambda: True)
    monkeypatch.setenv("RAAHAT_CHAIN_ID", "31337")
    monkeypatch.setenv("RAAHAT_TEST_INR", TOKEN)
    monkeypatch.setenv("RAAHAT_POOL", POOL)
    assert chain.load_config() is None
    monkeypatch.setenv("RAAHAT_CHAIN_ID", "84532")
    assert chain.load_config() is not None
