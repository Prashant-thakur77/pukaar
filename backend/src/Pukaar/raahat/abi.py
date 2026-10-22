"""The few contract functions the backend calls, as minimal ABIs (the full ABIs are in contracts/out/)."""

from __future__ import annotations

ERC20 = [
    {"type": "function", "name": "symbol", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "string"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "uint8"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
]

_RECORD = {"name": "r", "type": "tuple", "components": [
    {"name": "villageId", "type": "bytes32"}, {"name": "level", "type": "uint8"},
    {"name": "capHash", "type": "bytes32"}, {"name": "capUri", "type": "string"},
    {"name": "issuedAt", "type": "uint64"}, {"name": "exercise", "type": "bool"},
    {"name": "delivered", "type": "uint32"}, {"name": "acknowledged", "type": "uint32"},
    {"name": "afterActionHash", "type": "bytes32"}]}

ALERT_REGISTRY = [
    {"type": "function", "name": "anchorAlert", "stateMutability": "nonpayable",
     "inputs": [{"name": "alertId", "type": "bytes32"}, _RECORD], "outputs": []},
    {"type": "function", "name": "anchorOutcome", "stateMutability": "nonpayable",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "delivered", "type": "uint32"},
                {"name": "acknowledged", "type": "uint32"}, {"name": "afterActionHash", "type": "bytes32"}],
     "outputs": []},
]
