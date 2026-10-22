"""The Raahat chain client (web3.py).

Where it points: RAAHAT_RPC_URL and RAAHAT_CHAIN_ID, the contract addresses from RAAHAT_TEST_INR and
RAAHAT_POOL (template parameters on AWS), else the deployment file Deploy.s.sol writes
(RAAHAT_DEPLOYMENTS; in local mode contracts/deployments/anvil.json, so `make local` reads anvil and
needs no testnet). Moving to Arbitrum Sepolia or Polygon Amoy is an env change, nothing else.

Every call is wrapped: a failure (RPC down, wrong chain, odd answer) is logged, counted as
RaahatReadFailed (reads) or RaahatTxFailed (writes, alarmed) and returned as None. Nothing here ever
raises into a caller: an alert must go out even when the chain is down.

Writes are signed with the oracle key: RAAHAT_SIGNER_KEY in the environment (local runs), else the
SecureString at RAAHAT_SIGNER_PARAM (default /pukaar-raahat/<stage>/signer_key; outside /pukaar/* so
only the roles granted it can read it). On anvil with no key, anvil's unlocked oracle account sends.
The officer and pradhan attesters sign with their own keys, derived from the signer key per role
(keccak256(key || role)), so on chain they are different addresses from the oracle and from each other: one
key never counts as two attesters. On a testnet the backend holds all three after Cedar checks the person; a
production deployment gives each attester its own device key.
A transaction is sent and its hash returned; nothing waits for it to be mined.
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
# One try per call and a short timeout: a sick RPC costs seconds, never the minutes web3's default retries take.
RPC_TIMEOUT_SECONDS = 3
RECEIPT_WAIT_SECONDS = 20  # an officer's release, attestation or receipt waits this long to be mined
NONCE_TRIES = 3  # two Lambdas signing with one key can race for a nonce
# Contract name -> env var holding its address: required, then optional (absent: that feature is off).
ADDRESS_ENV = {"test_inr": "RAAHAT_TEST_INR", "pool": "RAAHAT_POOL"}
OPTIONAL_ADDRESS_ENV = {"alert_registry": "RAAHAT_ALERT_REGISTRY", "impact_attestation": "RAAHAT_IMPACT_ATTESTATION"}
KEY_CACHE_SECONDS = 300
_KEY_CACHE: dict[str, tuple[float, str]] = {}


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
    # The oracle (ORACLE_ROLE) address: on anvil with no key, the unlocked account that signs.
    oracle: str = ""


def _deployment_file() -> Path | None:
    raw = os.environ.get("RAAHAT_DEPLOYMENTS", "").strip()
    if raw.lower() == "off":
        return None
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
        rpc_url = os.environ.get("RAAHAT_RPC_URL", "").strip() or PUBLIC_RPCS.get(chain_id, "")
        if not chain_id or not rpc_url:
            return None
        if chain_id == 31337 and _aws_mode():  # anvil is for local mode only, never a deployed stack
            log(_LOG, "raahat config refused: anvil addresses on a deployed stack", 40)
            return None
        addresses = {name: Web3.to_checksum_address(os.environ.get(env) or dep[name])
                     for name, env in ADDRESS_ENV.items()}
        for name, env in OPTIONAL_ADDRESS_ENV.items():
            if os.environ.get(env) or dep.get(name):
                addresses[name] = Web3.to_checksum_address(os.environ.get(env) or dep[name])
        oracle = os.environ.get("RAAHAT_ORACLE") or dep.get("oracle") or ""
        is_contract = os.environ.get("RAAHAT_POOL_IS_CONTRACT", str(dep.get("pool_is_contract", False)))
        return ChainConfig(chain_id=chain_id, rpc_url=rpc_url, network=NETWORKS.get(chain_id, f"chain-{chain_id}"),
                           addresses=addresses, pool_is_contract=is_contract.strip().lower() in {"1", "true", "yes"},
                           public_rpc_url=os.environ.get("RAAHAT_PUBLIC_RPC_URL", "").strip()
                           or PUBLIC_RPCS.get(chain_id, ""),
                           oracle=Web3.to_checksum_address(oracle) if oracle else "")
    except Exception as exc:
        log(_LOG, "raahat config invalid", 40, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return None


def _provider_for(cfg: ChainConfig):
    from web3 import HTTPProvider

    return HTTPProvider(cfg.rpc_url, request_kwargs={"timeout": RPC_TIMEOUT_SECONDS}, exception_retry_configuration=None)


def _aws_mode() -> bool:
    return not get_settings().is_local


def _ssm_client():
    import boto3

    return boto3.client("ssm", region_name=get_settings().aws_region)


def signer_key() -> str | None:
    """The oracle's private key, or None. Never logged; SSM reads are cached for 5 minutes, failures never."""
    import time

    env = os.environ.get("RAAHAT_SIGNER_KEY", "").strip()
    if env:
        return env
    if not _aws_mode():
        return None
    name = os.environ.get("RAAHAT_SIGNER_PARAM", "").strip() or f"/pukaar-raahat/{get_settings().stage}/signer_key"
    hit = _KEY_CACHE.get(name)
    if hit and time.monotonic() - hit[0] < KEY_CACHE_SECONDS:
        return hit[1]
    value = _ssm_client().get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"].strip()
    _KEY_CACHE[name] = (time.monotonic(), value)
    return value


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

    def _signer(self, role: str = "oracle") -> tuple[str, Any]:
        """(sender address, local account or None for an unlocked anvil account) for "oracle", "officer" or
        "pradhan:<village id>"."""
        from eth_account import Account
        from eth_utils import keccak

        key = signer_key()
        if key:
            if role != "oracle":
                key = "0x" + keccak(bytes.fromhex(key.removeprefix("0x")) + role.encode()).hex()
            acct = Account.from_key(key)
            return acct.address, acct
        if self.cfg.chain_id == 31337:  # anvil only: its accounts are unlocked test accounts
            accounts = self.w3.eth.accounts
            if role == "oracle":
                return self.cfg.oracle or accounts[0], None
            return accounts[1 if role == "officer" else 2 + int.from_bytes(keccak(text=role)[:2], "big") % 7], None
        raise RuntimeError("no signer key configured (RAAHAT_SIGNER_KEY or the SSM parameter)")

    def address_of(self, role: str) -> str:
        return self._signer(role)[0]

    def _send(self, what: str, call: Any, role: str = "oracle") -> str | None:
        """Send one contract call as a transaction; its hash, or None (logged and counted) on any failure."""
        try:
            got = self.w3.eth.chain_id
            if got != self.cfg.chain_id:
                raise RuntimeError(f"RPC is on chain {got}, configured for {self.cfg.chain_id}")
            sender, acct = self._signer(role)
            from web3 import Web3

            for attempt in range(NONCE_TRIES):
                tx = call.build_transaction({"from": sender, "chainId": self.cfg.chain_id,
                                             "nonce": self.w3.eth.get_transaction_count(sender, "pending")})
                try:
                    if acct is not None:
                        sent = self.w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
                    else:
                        sent = self.w3.eth.send_transaction(tx)
                    return Web3.to_hex(sent)
                except Exception as exc:  # a nonce taken by a concurrent send: once more with a fresh one
                    text = str(exc).lower()
                    if attempt + 1 < NONCE_TRIES and any(k in text for k in ("nonce", "underpriced", "already known")):
                        log(_LOG, "raahat nonce retry", 30, what=what, attempt=attempt + 1)
                        continue
                    raise
            return None
        except Exception as exc:
            log(_LOG, "raahat tx failed", 40, what=what, network=self.cfg.network,
                error=f"{type(exc).__name__}: {str(exc)[:200]}")
            metric("RaahatTxFailed", 1)
            return None

    def confirm(self, tx: str, timeout: float = RECEIPT_WAIT_SECONDS) -> str:
        """"mined" (status 1), "reverted" (status 0, counted) or "pending" (not mined within timeout, or unknown)."""
        from web3.exceptions import TimeExhausted

        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx, timeout=timeout, poll_latency=1)
        except TimeExhausted:
            return "pending"
        except Exception as exc:
            log(_LOG, "raahat receipt read failed", 30, tx=tx, error=f"{type(exc).__name__}: {str(exc)[:120]}")
            return "pending"
        if int(receipt["status"]) == 1:
            return "mined"
        log(_LOG, "raahat tx reverted", 40, tx=tx, network=self.cfg.network)
        metric("RaahatTxFailed", 1)
        return "reverted"

    def anchor_alert(self, alert_key: bytes, record: tuple) -> str | None:
        reg = self.w3.eth.contract(address=self.cfg.addresses["alert_registry"], abi=abi.ALERT_REGISTRY)
        return self._send("anchor_alert", reg.functions.anchorAlert(alert_key, record))

    def anchor_outcome(self, alert_key: bytes, delivered: int, acknowledged: int, report_hash: bytes) -> str | None:
        reg = self.w3.eth.contract(address=self.cfg.addresses["alert_registry"], abi=abi.ALERT_REGISTRY)
        return self._send("anchor_outcome", reg.functions.anchorOutcome(alert_key, delivered, acknowledged,
                                                                        report_hash))

    def _pool(self) -> Any:
        if not self.cfg.pool_is_contract:
            raise RuntimeError("the pool is not the ReliefPool contract yet (RAAHAT_POOL_IS_CONTRACT)")
        return self.w3.eth.contract(address=self.cfg.addresses["pool"], abi=abi.RELIEF_POOL)

    def release(self, alert_key: bytes, tier: int) -> str | None:
        try:
            pool = self._pool()
        except Exception as exc:
            log(_LOG, "raahat tx failed", 40, what="release", network=self.cfg.network, error=str(exc)[:200])
            metric("RaahatTxFailed", 1)
            return None
        return self._send("release", pool.functions.release(alert_key, tier))

    def set_households(self, village_key: bytes, root: bytes, count: int) -> str | None:
        return self._send("set_households", self._pool().functions.setHouseholds(village_key, root, count))

    def set_cash_out_agent(self, village_key: bytes, agent: str) -> str | None:
        return self._send("set_cash_out_agent", self._pool().functions.setCashOutAgent(village_key, agent))

    def relief_state(self, village_key: bytes, alert_key: bytes, exercise: bool) -> dict | None:
        """Everything the ReliefPool checks for a release, read now: the code's pre-check mirrors the contract."""
        def read() -> dict:
            pool = self._pool()
            f = pool.functions
            token = self.w3.eth.contract(address=self.cfg.addresses["test_inr"], abi=abi.ERC20)
            min_level, amount_a, amount_c, cooldown = f.rule().call()
            agent = f.cashOutAgent(village_key).call()
            confirmer = f.confirmation().call()
            confirmed = None
            if int(confirmer, 16) != 0:
                confirmed = self.w3.eth.contract(address=confirmer, abi=abi.CONFIRMATION).functions.isConfirmed(
                    alert_key).call()
            return {
                "sealed": f.rulesSealed().call(), "sealed_at": f.sealedAt().call(),
                "allow_exercise": f.allowExercisePayout().call(),
                "rule": {"min_level": min_level, "amount_anticipatory_wei": amount_a,
                         "amount_confirmed_wei": amount_c, "cooldown_hours": cooldown},
                "households": f.householdCount(village_key).call(),
                "agent": None if int(agent, 16) == 0 else agent,
                "balance_wei": token.functions.balanceOf(pool.address).call(),
                "released": {1: f.released(alert_key, 1).call(), 2: f.released(alert_key, 2).call()},
                "last_anticipatory": f.lastAnticipatory(village_key, exercise).call(),
                "now": self.w3.eth.get_block("latest")["timestamp"], "confirmed": confirmed,
            }
        return self._safe("relief_state", read)

    def _attestation(self) -> Any:
        return self.w3.eth.contract(address=self.cfg.addresses["impact_attestation"], abi=abi.IMPACT_ATTESTATION)

    def attest(self, alert_key: bytes, who: int, severity: int, evidence_hash: bytes, *, village_id: str = "") -> str | None:
        """who: 0 pradhan (signs with that village's pradhan key), 1 officer, 2 satellite (the oracle)."""
        role = {0: f"pradhan:{village_id}", 1: "officer", 2: "oracle"}[who]
        try:
            call = self._attestation().functions.attest(alert_key, who, severity, evidence_hash)
        except Exception as exc:
            log(_LOG, "raahat tx failed", 40, what="attest", network=self.cfg.network, error=str(exc)[:200])
            metric("RaahatTxFailed", 1)
            return None
        return self._send("attest", call, role)

    def read_attestations(self, alert_key: bytes) -> dict | None:
        def read() -> dict:
            f = self._attestation().functions
            out = {}
            for who in (0, 1, 2):
                by, severity, evidence, at = f.attestations(alert_key, who).call()
                if int(by, 16):
                    out[who] = {"by": by, "severity": severity, "evidence_hash": "0x" + bytes(evidence).hex(), "at": at}
            return {"attestations": out, "confirmed": f.isConfirmed(alert_key).call()}
        return self._safe("read_attestations", read)

    def household_root(self, village_key: bytes) -> bytes | None:
        return self._safe("household_root", lambda: bytes(self._pool().functions.households(village_key).call()))

    def receipt(self, alert_key: bytes, household: bytes, proof: list[bytes], upi_ref_hash: bytes) -> str | None:
        """Signed by the oracle key: on testnet the cash-out agent is the backend, holding relief for the pradhan."""
        return self._send("receipt", self._pool().functions.receipt(alert_key, household, proof, upi_ref_hash))

    def setup_attesters(self, village_ids: list[str]) -> list[str]:
        """Grant OFFICER_ROLE and each village's pradhan role to the derived keys, and give each a little gas.
        Idempotent: only missing roles are granted. Returns what was done."""
        f = self._attestation().functions
        done = []
        targets = [("officer", f.OFFICER_ROLE().call())]
        targets += [(f"pradhan:{v}", f.pradhanRole(anchor_key(v)).call()) for v in village_ids]
        for role, role_id in targets:
            who = self.address_of(role)
            if not f.hasRole(role_id, who).call():
                done.append(f"grant {role} {who}: {self._send('grant_role', f.grantRole(role_id, who))}")
            if self.w3.eth.get_balance(who) < 2 * 10**14 and signer_key():
                sender, acct = self._signer()
                tx = {"from": sender, "to": who, "value": 10**15, "chainId": self.cfg.chain_id, "gas": 21000,
                      "nonce": self.w3.eth.get_transaction_count(sender, "pending"),
                      "maxFeePerGas": self.w3.eth.gas_price * 2, "maxPriorityFeePerGas": self.w3.eth.max_priority_fee}
                sent = self.w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
                done.append(f"gas {role} {who}: 0x{bytes(sent).hex()}")
        return done

    def latest_block(self) -> int | None:
        return self._safe("latest_block", lambda: int(self.w3.eth.block_number))

    def read_events(self, from_block: int, to_block: int) -> list[dict] | None:
        """Events of the Raahat contracts in [from_block, to_block] (keep the range within what the RPC allows:
        the public Base endpoint serves at most 200 blocks)."""
        from eth_abi import decode
        from eth_utils import keccak
        from web3 import Web3

        topics = {"0x" + keccak(text=sig).hex(): name for sig, name in EVENTS.items()}

        def read() -> list[dict]:
            logs = self.w3.eth.get_logs({"address": list(self.cfg.addresses.values()),
                                         "fromBlock": from_block, "toBlock": to_block})
            out = []
            for lg in logs:
                name = topics.get(Web3.to_hex(lg["topics"][0])) if lg["topics"] else None
                if name is None:
                    continue
                args: dict[str, Any] = {}
                if name == "Funded":
                    args = {"donor": Web3.to_checksum_address(bytes(lg["topics"][1])[-20:]),
                            "amount": str(decode(["uint256"], bytes(lg["data"]))[0])}
                elif name in ALERT_EVENTS:
                    args = {"alert_key": Web3.to_hex(lg["topics"][1])}
                out.append({"event": name, "block": int(lg["blockNumber"]), "log_index": int(lg["logIndex"]),
                            "tx": Web3.to_hex(lg["transactionHash"]), "args": args})
            return out
        return self._safe("read_events", read)

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
                "rule": self._rule() if self.cfg.pool_is_contract else None,
            }
        return self._safe("read_pool", read)

    def _rule(self) -> dict:
        f = self._pool().functions
        min_level, amount_a, amount_c, cooldown = f.rule().call()
        return {"min_level": min_level, "amount_anticipatory_wei": str(amount_a), "amount_confirmed_wei": str(amount_c),
                "cooldown_hours": cooldown, "sealed": f.rulesSealed().call(), "sealed_at": f.sealedAt().call(),
                "allow_exercise": f.allowExercisePayout().call()}


def anchor_key(village_id: str) -> bytes:
    from eth_utils import keccak

    return keccak(text=village_id)


# Every event the four contracts emit; the indexer stores each with its alert key when it has one.
EVENTS = {
    "AlertAnchored(bytes32,bytes32,uint8,bool,bytes32)": "AlertAnchored",
    "OutcomeAnchored(bytes32,uint32,uint32,bytes32)": "OutcomeAnchored",
    "Funded(address,uint256)": "Funded",
    "RuleSet(uint8,uint256,uint256,uint32)": "RuleSet",
    "RulesSealed(uint64)": "RulesSealed",
    "HouseholdsSet(bytes32,bytes32,uint32)": "HouseholdsSet",
    "CashOutAgentSet(bytes32,address)": "CashOutAgentSet",
    "Released(bytes32,bytes32,uint8,uint32,uint256,bool)": "Released",
    "PayoutReceipt(bytes32,bytes32,bytes32)": "PayoutReceipt",
    "Attested(bytes32,uint8,address,uint8,bytes32)": "Attested",
    "Confirmed(bytes32)": "Confirmed",
}
ALERT_EVENTS = {"AlertAnchored", "OutcomeAnchored", "Released", "PayoutReceipt", "Attested", "Confirmed"}


def client() -> RaahatChain | None:
    cfg = load_config()
    return RaahatChain(cfg, provider=_provider_for(cfg)) if cfg else None
