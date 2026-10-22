// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {TestINR} from "../src/TestINR.sol";
import {ReliefPool} from "../src/ReliefPool.sol";

/// Mints RAAHAT_FUND_TINR whole tINR (default 500000) to the broadcaster and funds the ReliefPool with it through
/// fund(), as a donor would, so the Funded event is on the ledger. Test money only: a real deployment takes a
/// real stable from real donors.
contract Fund is Script {
    using stdJson for string;

    /// The broadcaster: RAAHAT_DEPLOYER_KEY from the environment (testnet), else the unlocked --sender (anvil).
    function _begin() internal returns (address) {
        uint256 key = vm.envOr("RAAHAT_DEPLOYER_KEY", uint256(0));
        if (key == 0) {
            vm.startBroadcast();
            return msg.sender;
        }
        vm.startBroadcast(key);
        return vm.addr(key);
    }

    function run() external {
        string memory network = vm.envOr("RAAHAT_NETWORK", string("anvil"));
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/deployments/", network, ".json"));
        TestINR token = TestINR(json.readAddress(".test_inr"));
        address pool = json.readAddress(".pool");
        uint256 amount = vm.envOr("RAAHAT_FUND_TINR", uint256(500_000)) * 1 ether;
        address sender = _begin();
        token.mint(sender, amount);
        token.approve(pool, amount);
        ReliefPool(pool).fund(amount);
        vm.stopBroadcast();
    }
}
