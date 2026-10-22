// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title TestINR ("tINR")
/// @notice A testnet stand-in for an INR stablecoin. It has no value and is named so. Only the
///         deployer (MINTER_ROLE) mints; there is no burn, pause, permit or upgrade path.
///         A real deployment uses a licensed INR stable or a bank/UPI rail instead (PLAN.md §1.3).
contract TestINR is ERC20, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    constructor() ERC20("Test INR (testnet only, no value)", "tINR") {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(MINTER_ROLE, msg.sender);
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }
}
