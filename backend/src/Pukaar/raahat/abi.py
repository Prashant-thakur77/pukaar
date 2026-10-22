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
