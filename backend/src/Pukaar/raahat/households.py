"""Households as salted hashes, one Merkle root per village (PLAN.md §2.2, ReliefPool.households).

household = keccak256(abi.encode(keccak256(villageId), HMAC-SHA256(salt, householdNo)))
leaf      = keccak256(bytes.concat(keccak256(abi.encode(household))))   (OpenZeppelin's double hash)
Pairs are hashed sorted, as MerkleProof.verify expects; an odd node is carried up a level unpaired.

Until a household register exists, each registered recipient row (a Telegram chat id, a voice-only
"v_..." id or a demo "stub-..." id) is one household and its id is the householdNo. The id is only ever
an HMAC input: names, phones and chat ids never leave DynamoDB, and nothing here prints them.

The salt is the SecureString raahat_household_salt (core/secrets.py). Local mode, where nothing is
secret, uses LOCAL_SALT so a root built in one process matches the proofs built in another.

`make raahat-seed-households` prints each village's root and count. Writing the roots to ReliefPool
comes with the contract (PLAN.md Step 2).
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
    hashes = sorted({household_hash(village_id, r.id, salt_) for r in recipients if r.village_id == village_id})
    tree = VillageTree(village_id=village_id, households=hashes)
    if hashes:
        layer = sorted(leaf(h) for h in hashes)
        tree.layers = [layer]
        while len(layer) > 1:
            layer = [_pair(layer[i], layer[i + 1]) if i + 1 < len(layer) else layer[i]
                     for i in range(0, len(layer), 2)]
            tree.layers.append(layer)
    return tree


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
    repo = get_repo()
    for v in repo.list_villages():
        print(json.dumps(village_tree(v.id, repo.list_recipients(v.id), key).summary()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
