// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {TestINR} from "../src/TestINR.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";

/// Deploys the Raahat contracts and writes their addresses to deployments/<network>.json, which the
/// backend (RAAHAT_* env or this file in local mode) and `make raahat-fund` read.
///   anvil:        make raahat-deploy                       (unlocked anvil account, no key anywhere)
///   base-sepolia: make raahat-deploy RAAHAT_NETWORK=base-sepolia   (RAAHAT_DEPLOYER_KEY from .env.deploy.local)
/// Until ReliefPool exists (PLAN.md Step 2) the pool is the deployer's own address: "pool_is_contract": false.
/// RAAHAT_ORACLE: the Pukaar workflow's signer address (ORACLE_ROLE); defaults to the deployer.
contract Deploy is Script {
    using stdJson for string;

    function run() external {
        address deployer = msg.sender;
        address oracle = vm.envOr("RAAHAT_ORACLE", deployer);
        vm.startBroadcast();
        TestINR token = new TestINR();
        AlertRegistry registry = new AlertRegistry(oracle);
        vm.stopBroadcast();

        string memory k = "deployment";
        k.serialize("network", network(block.chainid));
        k.serialize("chain_id", block.chainid);
        k.serialize("deployer", deployer);
        k.serialize("deployed_at_block", block.number);
        k.serialize("test_inr", address(token));
        k.serialize("alert_registry", address(registry));
        k.serialize("oracle", oracle);
        k.serialize("pool_is_contract", false);
        string memory out = k.serialize("pool", deployer);
        out.write(string.concat(vm.projectRoot(), "/deployments/", network(block.chainid), ".json"));
    }

    function network(uint256 chainId) public pure returns (string memory) {
        if (chainId == 31337) return "anvil";
        if (chainId == 84532) return "base-sepolia";
        if (chainId == 421614) return "arbitrum-sepolia";
        if (chainId == 80002) return "polygon-amoy";
        revert("Deploy: unknown chain id");
    }
}
