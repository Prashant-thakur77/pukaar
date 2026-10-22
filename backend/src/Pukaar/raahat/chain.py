"""The Raahat chain client (web3.py), read-only for now.

Where it points: RAAHAT_RPC_URL and RAAHAT_CHAIN_ID, the contract addresses from RAAHAT_TEST_INR and
RAAHAT_POOL (template parameters on AWS), else the deployment file Deploy.s.sol writes
(RAAHAT_DEPLOYMENTS; in local mode contracts/deployments/anvil.json, so `make local` reads anvil and
needs no testnet). Moving to Arbitrum Sepolia or Polygon Amoy is an env change, nothing else.

Every call is wrapped: a failure (RPC down, wrong chain, odd answer) is logged, counted as
RaahatReadFailed and returned as None. Nothing here ever raises into a caller.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

from Pukaar.core.config import get_settings
from Pukaar.core.log import get_logger, log, metric
from Pukaar.raahat import abi

_LOG = get_logger("raahat")
T = TypeVar("T")

NETWORKS = {31337: "anvil", 84532: "base-sepolia", 421614: "arbitrum-sepolia", 80002: "polygon-amoy"}
EXPLORERS = {84532: "https://sepolia.basescan.org", 421614: "https://sepolia.arbiscan.io",
             80002: "https://amoy.polygonscan.com"}
ANVIL_RPC = "http://127.0.0.1:8545"
# What the browser reads the chain with. RAAHAT_RPC_URL may carry a provider key, so it never leaves the
# backend; the page gets RAAHAT_PUBLIC_RPC_URL, else the chain's own public endpoint.
PUBLIC_RPCS = {31337: ANVIL_RPC, 84532: "https://sepolia.base.org", 421614: "https://sepolia-rollup.arbitrum.io/rpc",
               80002: "https://rpc-amoy.polygon.technology"}
RPC_TIMEOUT_SECONDS = 5
# Contract name -> env var holding its address. Later steps add the registry, pool and attestation.
ADDRESS_ENV = {"test_inr": "RAAHAT_TEST_INR", "pool": "RAAHAT_POOL"}


def explorer_url(chain_id: int) -> str | None:
    return EXPLORERS.get(chain_id)


@dataclass(frozen=True)
class ChainConfig:
    chain_id: int
    rpc_url: str
    network: str
    addresses: dict[str, str] = field(default_factory=dict)
    # False until ReliefPool is deployed: the pool is then the deployer's own address (PLAN.md Step 0).
    pool_is_contract: bool = False
    public_rpc_url: str = ""


def _deployment_file() -> Path | None:
    raw = os.environ.get("RAAHAT_DEPLOYMENTS", "").strip()
    if raw:
        return Path(raw)
    if get_settings().is_local:  # backend/src/Pukaar/raahat/chain.py -> the repository root is parents[4]
        return Path(__file__).resolve().parents[4] / "contracts" / "deployments" / "anvil.json"
    return None


def load_config() -> ChainConfig | None:
    """None when Raahat is not configured (or misconfigured: logged). Read on every call, so a deploy made
    after the API started is picked up."""
    from web3 import Web3

    try:
        dep: dict[str, Any] = {}
        if not all(os.environ.get(v) for v in ADDRESS_ENV.values()):
            path = _deployment_file()
            if path is None or not path.is_file():
                return None
            dep = json.loads(path.read_text(encoding="utf-8"))
        chain_id = int(os.environ.get("RAAHAT_CHAIN_ID") or dep.get("chain_id") or 0)
        rpc_url = os.environ.get("RAAHAT_RPC_URL", "").strip() or (ANVIL_RPC if chain_id == 31337 else "")
        if not chain_id or not rpc_url:
            return None
        addresses = {name: Web3.to_checksum_address(os.environ.get(env) or dep[name])
                     for name, env in ADDRESS_ENV.items()}
        is_contract = os.environ.get("RAAHAT_POOL_IS_CONTRACT", str(dep.get("pool_is_contract", False)))
        return ChainConfig(chain_id=chain_id, rpc_url=rpc_url, network=NETWORKS.get(chain_id, f"chain-{chain_id}"),
                           addresses=addresses, pool_is_contract=is_contract.strip().lower() in {"1", "true", "yes"},
                           public_rpc_url=os.environ.get("RAAHAT_PUBLIC_RPC_URL", "").strip()
                           or PUBLIC_RPCS.get(chain_id, ""))
    except Exception as exc:
        log(_LOG, "raahat config invalid", 40, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return None


def _provider_for(cfg: ChainConfig):
    from web3 import HTTPProvider

    return HTTPProvider(cfg.rpc_url, request_kwargs={"timeout": RPC_TIMEOUT_SECONDS})


class RaahatChain:
    def __init__(self, cfg: ChainConfig, *, provider: Any = None):
        from web3 import Web3

        self.cfg = cfg
        self.w3 = Web3(provider if provider is not None else _provider_for(cfg))

    def _safe(self, what: str, fn: Callable[[], T]) -> T | None:
        try:
            got = self.w3.eth.chain_id
            if got != self.cfg.chain_id:
                raise RuntimeError(f"RPC is on chain {got}, configured for {self.cfg.chain_id}")
            return fn()
        except Exception as exc:
            log(_LOG, "raahat read failed", 40, what=what, network=self.cfg.network,
                error=f"{type(exc).__name__}: {str(exc)[:200]}")
            metric("RaahatReadFailed", 1)
            return None

    def read_pool(self) -> dict | None:
        """The pool's tINR balance (exact wei, as a string), the token and the block it was read at."""
        def read() -> dict:
            token = self.w3.eth.contract(address=self.cfg.addresses["test_inr"], abi=abi.ERC20)
            pool = self.cfg.addresses["pool"]
            return {
                "chain_id": self.cfg.chain_id, "network": self.cfg.network,
                "explorer": explorer_url(self.cfg.chain_id), "block": self.w3.eth.block_number,
                "token": {"address": token.address, "symbol": token.functions.symbol().call(),
                          "decimals": token.functions.decimals().call()},
                "pool": {"address": pool, "is_contract": self.cfg.pool_is_contract,
                         "balance_wei": str(token.functions.balanceOf(pool).call())},
            }
        return self._safe("read_pool", read)


def client() -> RaahatChain | None:
    cfg = load_config()
    return RaahatChain(cfg, provider=_provider_for(cfg)) if cfg else None
