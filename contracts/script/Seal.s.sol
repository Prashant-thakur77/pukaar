// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {ReliefPool} from "../src/ReliefPool.sol";

/// Seals the ReliefPool's rule for the season (make raahat-seal), after Deploy.s.sol and after every village's
/// households and cash-out agent are written: from now on no amount or threshold can change, and a village's
/// household list or agent changes only after a public delay of one cooldown.
contract Seal is Script {
    using stdJson for string;

    function run() external {
        string memory network = vm.envOr("RAAHAT_NETWORK", string("anvil"));
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/deployments/", network, ".json"));
        ReliefPool pool = ReliefPool(json.readAddress(".pool"));
        uint256 key = vm.envOr("RAAHAT_DEPLOYER_KEY", uint256(0)); // testnet; anvil uses the unlocked --sender
        if (key == 0) vm.startBroadcast();
        else vm.startBroadcast(key);
        pool.sealRules();
        vm.stopBroadcast();
    }
}
