"""Household Merkle tree (raahat/households.py): deterministic, salted, nothing personal in the output, and
proofs that verify the way OpenZeppelin's MerkleProof does (sorted pairs, double-hashed leaves)."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

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


# The Foundry tests (contracts/test/ReliefPool.t.sol) verify these proofs on chain: one fixture, two languages.
FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "test" / "fixtures" / "households.json"
FIXTURE_SALT = b"fixture-salt-not-a-secret"


def fixture() -> dict:
    tree = hh.village_tree("sujanpur", _people("sujanpur", [f"h{i}" for i in range(1, 6)]), FIXTURE_SALT)
    stranger = hh.household_hash("gohar", "h1", FIXTURE_SALT)
    return {
        "village_key": "0x" + hh.village_key("sujanpur").hex(),
        "root": "0x" + tree.root.hex(),
        "count": tree.count,
        "households": [{"hash": "0x" + h.hex(), "proof": ["0x" + p.hex() for p in tree.proof(h)]}
                       for h in tree.households],
        "stranger": {"hash": "0x" + stranger.hex(),
                     "proof": ["0x" + p.hex() for p in tree.proof(tree.households[0])]},
    }


def test_foundry_fixture_is_what_households_py_builds():
    """Regenerate with: python -c 'from tests.test_raahat_households import write_fixture; write_fixture()'"""
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == fixture()


def write_fixture() -> None:
    FIXTURE.write_text(json.dumps(fixture(), indent=1) + "\n", encoding="utf-8")


# -- the register and seeding it on chain --------------------------------------------------------------------
class FakePool:
    def __init__(self):
        self.calls = []
        self.cfg = type("C", (), {"oracle": "0x" + "cd" * 20, "network": "anvil"})()

    def set_households(self, village_key, root, count):
        self.calls.append(("households", village_key, root, count))
        return "0x01"

    def set_cash_out_agent(self, village_key, agent):
        self.calls.append(("agent", village_key, agent))
        return "0x02"


def test_register_adds_labelled_demo_households_off_prod(repo):
    reg = hh.register(repo, "sujanpur")
    assert len(reg) == 42
    assert sum(1 for no, demo in reg if demo) == 40
    assert all(no.startswith("demo-household-sujanpur-") for no, demo in reg if demo)


def test_prod_register_is_the_recipients_only(repo, monkeypatch):
    monkeypatch.setattr(hh, "_demo_allowed", lambda: False)
    assert len(hh.register(repo, "sujanpur")) == 2


def test_seed_writes_snapshot_and_chain_and_no_ids(repo):
    pool = FakePool()
    out = hh.seed(repo, pool, hh.LOCAL_SALT)
    suj = next(o for o in out if o["village_id"] == "sujanpur")
    assert suj["count"] == 42 and suj["households_tx"] == "0x01" and suj["agent_tx"] == "0x02"
    snap = hh.snapshot(repo, "sujanpur")
    assert snap["count"] == 42 and snap["root"] == suj["root"] and len(snap["hashes"]) == 42
    assert "stub-sujanpur-1" not in json.dumps(snap) and "demo-household" not in json.dumps(snap)
    key = hh.village_key("sujanpur")
    assert ("households", key, bytes.fromhex(suj["root"][2:]), 42) in pool.calls
    assert ("agent", key, pool.cfg.oracle) in pool.calls  # the demo cash-out agent: the backend's own signer


def test_snapshot_tree_rebuilds_the_same_proofs(repo):
    hh.seed(repo, None, hh.LOCAL_SALT)
    tree = hh.snapshot_tree(repo, "sujanpur")
    h = hh.household_hash("sujanpur", "stub-sujanpur-1", hh.LOCAL_SALT)
    assert "0x" + tree.root.hex() == hh.snapshot(repo, "sujanpur")["root"] and tree.proof(h)
