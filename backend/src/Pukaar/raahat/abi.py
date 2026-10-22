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

RELIEF_POOL = [
    {"type": "function", "name": "rulesSealed", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "sealedAt", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint64"}]},
    {"type": "function", "name": "allowExercisePayout", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "rule", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}, {"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}, {"name": "", "type": "uint32"}]},
    {"type": "function", "name": "confirmation", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "householdCount", "stateMutability": "view",
     "inputs": [{"name": "villageId", "type": "bytes32"}], "outputs": [{"name": "", "type": "uint32"}]},
    {"type": "function", "name": "households", "stateMutability": "view",
     "inputs": [{"name": "villageId", "type": "bytes32"}], "outputs": [{"name": "", "type": "bytes32"}]},
    {"type": "function", "name": "cashOutAgent", "stateMutability": "view",
     "inputs": [{"name": "villageId", "type": "bytes32"}], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "released", "stateMutability": "view",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "tier", "type": "uint8"}], "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "lastAnticipatory", "stateMutability": "view",
     "inputs": [{"name": "villageId", "type": "bytes32"}, {"name": "exercise", "type": "bool"}], "outputs": [{"name": "", "type": "uint64"}]},
    {"type": "function", "name": "receiptCount", "stateMutability": "view",
     "inputs": [{"name": "alertId", "type": "bytes32"}], "outputs": [{"name": "", "type": "uint32"}]},
    {"type": "function", "name": "release", "stateMutability": "nonpayable",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "tier", "type": "uint8"}], "outputs": []},
    {"type": "function", "name": "setHouseholds", "stateMutability": "nonpayable",
     "inputs": [{"name": "villageId", "type": "bytes32"}, {"name": "root", "type": "bytes32"}, {"name": "count", "type": "uint32"}], "outputs": []},
    {"type": "function", "name": "receipt", "stateMutability": "nonpayable",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "householdHash", "type": "bytes32"},
                {"name": "proof", "type": "bytes32[]"}, {"name": "upiRefHash", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "setCashOutAgent", "stateMutability": "nonpayable",
     "inputs": [{"name": "villageId", "type": "bytes32"}, {"name": "agent", "type": "address"}], "outputs": []},
]

CONFIRMATION = [
    {"type": "function", "name": "isConfirmed", "stateMutability": "view",
     "inputs": [{"name": "alertId", "type": "bytes32"}], "outputs": [{"name": "", "type": "bool"}]},
]

IMPACT_ATTESTATION = [
    {"type": "function", "name": "attest", "stateMutability": "nonpayable",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "who", "type": "uint8"},
                {"name": "severity", "type": "uint8"}, {"name": "evidenceHash", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "attestations", "stateMutability": "view",
     "inputs": [{"name": "alertId", "type": "bytes32"}, {"name": "who", "type": "uint8"}],
     "outputs": [{"name": "by", "type": "address"}, {"name": "severity", "type": "uint8"},
                 {"name": "evidenceHash", "type": "bytes32"}, {"name": "at", "type": "uint64"}]},
    {"type": "function", "name": "isConfirmed", "stateMutability": "view",
     "inputs": [{"name": "alertId", "type": "bytes32"}], "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "pradhanRole", "stateMutability": "pure",
     "inputs": [{"name": "villageId", "type": "bytes32"}], "outputs": [{"name": "", "type": "bytes32"}]},
    {"type": "function", "name": "OFFICER_ROLE", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "bytes32"}]},
    {"type": "function", "name": "hasRole", "stateMutability": "view",
     "inputs": [{"name": "role", "type": "bytes32"}, {"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "grantRole", "stateMutability": "nonpayable",
     "inputs": [{"name": "role", "type": "bytes32"}, {"name": "account", "type": "address"}], "outputs": []},
]
