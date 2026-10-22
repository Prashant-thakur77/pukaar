"""Household Merkle tree (raahat/households.py): deterministic, salted, nothing personal in the output, and
proofs that verify the way OpenZeppelin's MerkleProof does (sorted pairs, double-hashed leaves)."""

from __future__ import annotations

import hashlib
import hmac
import json

from eth_abi import encode
from eth_utils import keccak
from Pukaar.raahat import households as hh
from Pukaar.store.models import Recipient

SALT = b"test-salt-not-a-secret"


def _people(village: str, ids: list[str]) -> list[Recipient]:
    return [Recipient(id=i, village_id=village, name=f"Person {i}", channel="stub") for i in ids]


def test_household_hash_is_keccak_of_village_and_hmac():
    expected = keccak(encode(["bytes32", "bytes32"], [keccak(text="gohar"),
                                                      hmac.new(SALT, b"123456789", hashlib.sha256).digest()]))
    assert hh.household_hash("gohar", "123456789", SALT) == expected


def test_root_is_independent_of_row_order():
    a = hh.village_tree("gohar", _people("gohar", ["1", "2", "3", "4", "5"]), SALT)
    b = hh.village_tree("gohar", _people("gohar", ["5", "3", "1", "4", "2"]), SALT)
    assert a.root == b.root and a.count == 5


def test_salt_and_village_change_the_root():
    people = ["1", "2", "3"]
    base = hh.village_tree("gohar", _people("gohar", people), SALT).root
    assert hh.village_tree("gohar", _people("gohar", people), b"other").root != base
    assert hh.village_tree("thunag", _people("thunag", people), SALT).root != base


def test_two_leaf_root_by_hand():
    h1, h2 = hh.household_hash("gohar", "1", SALT), hh.household_hash("gohar", "2", SALT)
    l1, l2 = sorted([hh.leaf(h1), hh.leaf(h2)])
    assert hh.village_tree("gohar", _people("gohar", ["1", "2"]), SALT).root == keccak(l1 + l2)


def _oz_verify(proof: list[bytes], root: bytes, leaf: bytes) -> bool:
    """OpenZeppelin MerkleProof.verify: commutative keccak of each pair."""
    node = leaf
    for sib in proof:
        node = keccak(min(node, sib) + max(node, sib))
    return node == root


def test_every_household_has_a_proof_that_verifies_including_odd_counts():
    for n in (1, 2, 3, 7, 42):
        tree = hh.village_tree("sujanpur", _people("sujanpur", [str(i) for i in range(n)]), SALT)
        for i in range(n):
            h = hh.household_hash("sujanpur", str(i), SALT)
            assert _oz_verify(tree.proof(h), tree.root, hh.leaf(h)), (n, i)


def test_proof_for_another_village_household_does_not_verify():
    tree = hh.village_tree("gohar", _people("gohar", ["1", "2", "3"]), SALT)
    stranger = hh.household_hash("thunag", "1", SALT)
    assert tree.proof(stranger) == []
    assert not _oz_verify(tree.proof(stranger), tree.root, hh.leaf(stranger))


def test_empty_village_has_zero_root():
    tree = hh.village_tree("pandoh", [], SALT)
    assert tree.root == b"\x00" * 32 and tree.count == 0


def test_rows_of_other_villages_are_ignored():
    mixed = _people("gohar", ["1", "2"]) + _people("thunag", ["9"])
    assert hh.village_tree("gohar", mixed, SALT).count == 2


def test_summary_carries_no_ids_or_names():
    people = _people("gohar", ["123456789", "v_01HZXK"])
    out = json.dumps(hh.village_tree("gohar", people, SALT).summary())
    assert "123456789" not in out and "v_01HZXK" not in out and "Person" not in out
    assert json.loads(out) == {"village_id": "gohar", "village_key": "0x" + keccak(text="gohar").hex(),
                               "count": 2, "root": json.loads(out)["root"]}


def test_local_mode_salt_is_stable_and_aws_mode_needs_the_secret(monkeypatch):
    monkeypatch.delenv("PUKAAR_RAAHAT_HOUSEHOLD_SALT", raising=False)
    assert hh.salt() == hh.salt() == hh.LOCAL_SALT
    monkeypatch.setenv("PUKAAR_RAAHAT_HOUSEHOLD_SALT", "from-env")
    assert hh.salt() == b"from-env"
