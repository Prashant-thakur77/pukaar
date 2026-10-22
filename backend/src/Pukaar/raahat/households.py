"""Households as salted hashes, one Merkle root per village (PLAN.md §2.2, ReliefPool.households).

household = keccak256(abi.encode(keccak256(villageId), HMAC-SHA256(salt, householdNo)))
leaf      = keccak256(bytes.concat(keccak256(abi.encode(household))))   (OpenZeppelin's double hash)
Pairs are hashed sorted, as MerkleProof.verify expects; an odd node is carried up a level unpaired.

Until a household register exists, each registered recipient row (a Telegram chat id, a voice-only
"v_..." id or a demo "stub-..." id) is one household and its id is the householdNo. The id is only ever
an HMAC input: names, phones and chat ids never leave DynamoDB, and nothing here prints them.

The salt is the SecureString raahat_household_salt (core/secrets.py). Local mode, where nothing is
secret, uses LOCAL_SALT so a root built in one process matches the proofs built in another.

On non-prod stages the register adds labelled demo households (data/raahat/demo_households.json: no
phone, no name) so the testnet demo has a village's worth of households; prod registers recipients only.

`make raahat-seed-households` builds each village's tree, stores a snapshot of its hashes (never the ids)
at RAAHAT#HOUSEHOLDS#<village> / ROOT so later proofs match the root on chain, and, when the ReliefPool is
configured, sends setHouseholds and setCashOutAgent. On testnet the cash-out agent is the backend's own
signer, holding the village's relief for the pradhan (no wallets for pradhans); in production it is the
Business Correspondent's or pradhan's own account (RAAHAT_AGENT_<VILLAGE>).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Iterable

from eth_abi import encode
from eth_utils import keccak

from Pukaar.core.config import get_settings
from Pukaar.core.secrets import get_secret
from Pukaar.store.models import Recipient

LOCAL_SALT = b"pukaar-local-mode-household-salt (not a secret)"
ZERO = b"\x00" * 32


def salt() -> bytes | None:
    """None on AWS when the secret is not set: no root is built rather than one with a guessable salt."""
    value = get_secret("raahat_household_salt")
    if value:
        return value.encode()
    return LOCAL_SALT if get_settings().is_local else None


def village_key(village_id: str) -> bytes:
    return keccak(text=village_id)


def household_hash(village_id: str, household_no: str, salt_: bytes) -> bytes:
    mac = hmac.new(salt_, household_no.encode(), hashlib.sha256).digest()
    return keccak(encode(["bytes32", "bytes32"], [village_key(village_id), mac]))


def leaf(household: bytes) -> bytes:
    return keccak(keccak(encode(["bytes32"], [household])))


def _pair(a: bytes, b: bytes) -> bytes:
    return keccak(min(a, b) + max(a, b))


@dataclass
class VillageTree:
    village_id: str
    households: list[bytes]
    layers: list[list[bytes]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.households)

    @property
    def root(self) -> bytes:
        return self.layers[-1][0] if self.layers else ZERO

    def proof(self, household: bytes) -> list[bytes]:
        """The sibling path for one household; [] when it is not in this village's tree."""
        node = leaf(household)
        if not self.layers or node not in self.layers[0]:
            return []
        i, path = self.layers[0].index(node), []
        for layer in self.layers[:-1]:
            sib = i ^ 1
            if sib < len(layer):
                path.append(layer[sib])
            i //= 2
        return path

    def summary(self) -> dict:
        return {"village_id": self.village_id, "village_key": "0x" + village_key(self.village_id).hex(),
                "count": self.count, "root": "0x" + self.root.hex()}


def village_tree(village_id: str, recipients: Iterable[Recipient], salt_: bytes) -> VillageTree:
    return tree_of(village_id, {household_hash(village_id, r.id, salt_) for r in recipients
                                if r.village_id == village_id})


def tree_of(village_id: str, household_hashes: Iterable[bytes]) -> VillageTree:
    hashes = sorted(set(household_hashes))
    tree = VillageTree(village_id=village_id, households=hashes)
    if hashes:
        layer = sorted(leaf(h) for h in hashes)
        tree.layers = [layer]
        while len(layer) > 1:
            layer = [_pair(layer[i], layer[i + 1]) if i + 1 < len(layer) else layer[i]
                     for i in range(0, len(layer), 2)]
            tree.layers.append(layer)
    return tree


SNAPSHOT_PK, SNAPSHOT_SK = "RAAHAT#HOUSEHOLDS#", "ROOT"
DEMO_FILE = "raahat/demo_households.json"


def _demo_allowed() -> bool:
    return get_settings().stage != "prod"


def _demo_counts() -> dict[str, int]:
    path = get_settings().data_dir / DEMO_FILE
    if not path.is_file():
        return {}
    return {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def register(repo, village_id: str) -> list[tuple[str, bool]]:
    """(householdNo, is_demo) for every household of the village: its registered recipients, plus the labelled
    demo households off prod."""
    out = [(r.id, False) for r in repo.list_recipients(village_id)]
    if _demo_allowed():
        out += [(f"demo-household-{village_id}-{i:03d}", True) for i in range(1, _demo_counts().get(village_id, 0) + 1)]
    return out


def snapshot(repo, village_id: str) -> dict | None:
    item = repo._get(SNAPSHOT_PK + village_id, SNAPSHOT_SK)
    if not item:
        return None
    return {k: (int(v) if k in {"count", "demo"} else v) for k, v in item.items() if k not in {"pk", "sk"}}


def snapshot_tree(repo, village_id: str) -> VillageTree | None:
    snap = snapshot(repo, village_id)
    return tree_of(village_id, (bytes.fromhex(h[2:]) for h in snap["hashes"])) if snap else None


def seed(repo, pool, salt_: bytes) -> list[dict]:
    """Build, snapshot and (with a pool client) write every village's root and cash-out agent."""
    import os

    from Pukaar.core import clock

    out = []
    for v in repo.list_villages():
        reg = register(repo, v.id)
        tree = tree_of(v.id, (household_hash(v.id, no, salt_) for no, _ in reg))
        row = {**tree.summary(), "demo": sum(1 for _, demo in reg if demo), "households_tx": None, "agent_tx": None}
        if pool is not None:
            agent = os.environ.get(f"RAAHAT_AGENT_{v.id.upper()}", "").strip() or pool.cfg.oracle
            row["households_tx"] = pool.set_households(village_key(v.id), tree.root, tree.count)
            row["agent_tx"] = pool.set_cash_out_agent(village_key(v.id), agent) if agent else None
        repo._put({"pk": SNAPSHOT_PK + v.id, "sk": SNAPSHOT_SK, **row, "at": clock.iso(clock.now()),
                   "hashes": ["0x" + h.hex() for h in tree.households]})
        out.append(row)
    return out


def main() -> int:
    s = get_settings()
    if s.is_local:
        from Pukaar.core.local import start_local_aws

        start_local_aws()
    from Pukaar.store.repo import get_repo

    key = salt()
    if key is None:
        print("raahat_household_salt is not set in SSM: no roots built (scripts/put_secrets.sh).")
        return 2
    from Pukaar.raahat import relief

    pool = relief._client()
    if pool is None:
        print("ReliefPool not configured: roots are built and stored, not written on chain.")
    for row in seed(get_repo(), pool, key):
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
