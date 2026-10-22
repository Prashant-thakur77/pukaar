// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {TestINR} from "../src/TestINR.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";
import {ReliefPool} from "../src/ReliefPool.sol";
import {ImpactAttestation} from "../src/ImpactAttestation.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// Deploys the Raahat contracts and writes their addresses to deployments/<network>.json, which the
/// backend (RAAHAT_* env or this file in local mode) and `make raahat-fund` read.
///   anvil:        make raahat-deploy                       (unlocked anvil account, no key anywhere)
///   base-sepolia: make raahat-deploy RAAHAT_NETWORK=base-sepolia   (RAAHAT_DEPLOYER_KEY from .env.deploy.local)
/// RAAHAT_ORACLE: the backend signer's address (ORACLE_ROLE on the registry and the attestation, DDMA_ROLE on the
/// pool, so an officer's one tap in the console releases); defaults to the deployer. RAAHAT_OFFICER_ATTESTER gets
/// OFFICER_ROLE on the attestation; pradhans' roles are granted per village later (raahat/attest.py setup).
/// RAAHAT_REUSE_TEST_INR / RAAHAT_REUSE_REGISTRY keep deployed contracts (their anchors and balances stay valid);
/// the pool is always new, because its attestation contract is fixed at construction.
/// The relief rule is set and sealed here, before any flood: illustrative amounts, SDRF norms to be mapped
/// with the DDMA. 1 tINR stands for Rs 1. RAAHAT_ALLOW_EXERCISE=false for anything but a testnet demo.
contract Deploy is Script {
    using stdJson for string;

    function run() external {
        address deployer = msg.sender;
        address oracle = vm.envOr("RAAHAT_ORACLE", deployer);
        bool allowExercise = vm.envOr("RAAHAT_ALLOW_EXERCISE", true);
        address reuseToken = vm.envOr("RAAHAT_REUSE_TEST_INR", address(0));
        address reuseRegistry = vm.envOr("RAAHAT_REUSE_REGISTRY", address(0));
        address officerAttester = vm.envOr("RAAHAT_OFFICER_ATTESTER", address(0));
        vm.startBroadcast();
        TestINR token = reuseToken == address(0) ? new TestINR() : TestINR(reuseToken);
        AlertRegistry registry = reuseRegistry == address(0) ? new AlertRegistry(oracle) : AlertRegistry(reuseRegistry);
        ImpactAttestation attestation = new ImpactAttestation(registry, oracle);
        if (officerAttester != address(0)) attestation.grantRole(attestation.OFFICER_ROLE(), officerAttester);
        ReliefPool pool = new ReliefPool(IERC20(address(token)), registry, attestation, allowExercise, deployer);
        pool.setRule(ReliefPool.Rule({minLevelAnticipatory: 2, amountAnticipatory: 1_500 ether, amountConfirmed: 4_000 ether, cooldownHours: 72}));
        pool.sealRules();
        if (oracle != deployer) pool.grantRole(pool.DDMA_ROLE(), oracle);
        vm.stopBroadcast();

        string memory k = "deployment";
        k.serialize("network", network(block.chainid));
        k.serialize("chain_id", block.chainid);
        k.serialize("deployer", deployer);
        k.serialize("deployed_at_block", block.number);
        k.serialize("test_inr", address(token));
        k.serialize("alert_registry", address(registry));
        k.serialize("impact_attestation", address(attestation));
        k.serialize("oracle", oracle);
        k.serialize("allow_exercise_payout", allowExercise);
        k.serialize("pool_is_contract", true);
        string memory out = k.serialize("pool", address(pool));
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
