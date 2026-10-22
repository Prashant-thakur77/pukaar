// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {TestINR} from "../src/TestINR.sol";
import {ReliefPool} from "../src/ReliefPool.sol";

/// Mints RAAHAT_FUND_TINR whole tINR (default 500000) to the deployer and funds the ReliefPool with it through
/// fund(), as a donor would, so the Funded event is on the ledger. Test money only: a real deployment takes a
/// real stable from real donors.
contract Fund is Script {
    using stdJson for string;

    function run() external {
        string memory network = vm.envOr("RAAHAT_NETWORK", string("anvil"));
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/deployments/", network, ".json"));
        TestINR token = TestINR(json.readAddress(".test_inr"));
        address pool = json.readAddress(".pool");
        uint256 amount = vm.envOr("RAAHAT_FUND_TINR", uint256(500_000)) * 1 ether;
        vm.startBroadcast();
        token.mint(msg.sender, amount);
        token.approve(pool, amount);
        ReliefPool(pool).fund(amount);
        vm.stopBroadcast();
    }
}
