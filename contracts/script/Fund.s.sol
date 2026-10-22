// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {TestINR} from "../src/TestINR.sol";

/// Mints RAAHAT_FUND_TINR whole tINR (default 500000) into the pool named in deployments/<network>.json.
/// Test money only: on a real deployment a donor transfers a real stable through ReliefPool.fund().
contract Fund is Script {
    using stdJson for string;

    function run() external {
        string memory network = vm.envOr("RAAHAT_NETWORK", string("anvil"));
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/deployments/", network, ".json"));
        TestINR token = TestINR(json.readAddress(".test_inr"));
        address pool = json.readAddress(".pool");
        uint256 amount = vm.envOr("RAAHAT_FUND_TINR", uint256(500_000)) * 1 ether;
        vm.startBroadcast();
        token.mint(pool, amount);
        vm.stopBroadcast();
    }
}
