// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";
import {ReliefPool} from "../src/ReliefPool.sol";
import {TestINR} from "../src/TestINR.sol";
import {FakeConfirmation} from "./ReliefPool.t.sol";

/// Review fixes: the confirmed tranche has its own cooldown, and after the seal a village's household count and
/// cash-out agent change only after a public delay (the cooldown), so neither can be moved just before a release.
contract ReliefPoolReviewTest is Test {
    TestINR internal token;
    AlertRegistry internal registry;
    FakeConfirmation internal confirmation;
    ReliefPool internal pool;
    address internal ddma = makeAddr("ddma");
    address internal oracle = makeAddr("oracle");
    address internal agent = makeAddr("agent");
    address internal thief = makeAddr("thief");
    bytes32 internal constant V = keccak256("pandoh");

    event HouseholdsScheduled(bytes32 indexed villageId, bytes32 root, uint32 count, uint64 effectiveAt);
    event CashOutAgentScheduled(bytes32 indexed villageId, address agent, uint64 effectiveAt);

    function setUp() public {
        vm.warp(1_000_000);
        token = new TestINR();
        registry = new AlertRegistry(oracle);
        confirmation = new FakeConfirmation();
        pool = new ReliefPool(IERC20(address(token)), registry, confirmation, true, ddma);
        token.mint(address(pool), 10_000_000 ether);
        vm.startPrank(ddma);
        pool.setHouseholds(V, bytes32(uint256(1)), 30);
        pool.setCashOutAgent(V, agent);
        pool.setRule(ReliefPool.Rule(2, 1_500 ether, 4_000 ether, 72));
        pool.sealRules();
        vm.stopPrank();
    }

    function _anchor(bytes32 id, bool exercise) internal {
        AlertRegistry.AlertRecord memory r;
        r.villageId = V;
        r.level = 3;
        r.capHash = keccak256(abi.encode(id));
        r.capUri = "u";
        r.issuedAt = 1;
        r.exercise = exercise;
        vm.prank(oracle);
        registry.anchorAlert(id, r);
        confirmation.set(id, true);
    }

    function test_confirmedTrancheOncePerVillagePerCooldown() public {
        bytes32 a = keccak256("watch-then-warning");
        bytes32 b = keccak256("then-critical");
        bytes32 replay = keccak256("replay");
        _anchor(a, false);
        _anchor(b, false);
        _anchor(replay, true);
        vm.startPrank(ddma);
        pool.release(a, 2);
        vm.expectRevert(bytes("ReliefPool: village is in its cooldown"));
        pool.release(b, 2); // the same flood's next alert does not pay the confirmed tranche again
        pool.release(replay, 2); // exercises keep their own cooldown
        vm.warp(block.timestamp + 72 hours);
        pool.release(b, 2);
        vm.stopPrank();
    }

    function test_householdsAfterTheSealWaitOutTheDelay() public {
        bytes32 a = keccak256("a");
        _anchor(a, false);
        vm.expectEmit(true, false, false, true, address(pool));
        emit HouseholdsScheduled(V, bytes32(uint256(2)), 100_000, uint64(block.timestamp + 72 hours));
        vm.prank(ddma);
        pool.setHouseholds(V, bytes32(uint256(2)), 100_000);
        assertEq(pool.householdCount(V), 30); // not yet
        vm.prank(ddma);
        pool.release(a, 1);
        assertEq(token.balanceOf(agent), 30 * 1_500 ether);
        vm.warp(block.timestamp + 72 hours);
        pool.applyDue(V); // anyone may apply a change whose delay has passed
        assertEq(pool.householdCount(V), 100_000);
        assertEq(pool.households(V), bytes32(uint256(2)));
    }

    function test_agentAfterTheSealWaitsOutTheDelayAndReleasesApplyDueChanges() public {
        vm.expectEmit(true, false, false, true, address(pool));
        emit CashOutAgentScheduled(V, thief, uint64(block.timestamp + 72 hours));
        vm.prank(ddma);
        pool.setCashOutAgent(V, thief);
        bytes32 a = keccak256("a");
        _anchor(a, false);
        vm.prank(ddma);
        pool.release(a, 1);
        assertEq(token.balanceOf(agent), 30 * 1_500 ether); // still the old agent
        assertEq(token.balanceOf(thief), 0);
        vm.warp(block.timestamp + 72 hours + 1);
        bytes32 b = keccak256("b");
        _anchor(b, false);
        vm.prank(ddma);
        pool.release(b, 1); // the due change is applied by the release itself
        assertEq(pool.cashOutAgent(V), thief);
        assertEq(token.balanceOf(thief), 30 * 1_500 ether);
    }

    function test_applyDueBeforeTheDelayChangesNothing() public {
        vm.prank(ddma);
        pool.setHouseholds(V, bytes32(uint256(9)), 99);
        pool.applyDue(V);
        assertEq(pool.householdCount(V), 30);
        (bytes32 root, uint32 count, uint64 at) = pool.pendingHouseholds(V);
        assertEq(root, bytes32(uint256(9)));
        assertEq(count, 99);
        assertEq(at, uint64(block.timestamp + 72 hours));
    }
}

contract ReliefPoolExerciseResetTest is ReliefPoolReviewTest {
    event ExerciseCooldownCleared(bytes32 indexed villageId);

    /// Replays are re-run (a demo, a training): the DDMA may clear a village's exercise cooldowns, never its live ones.
    function test_exerciseCooldownsCanBeClearedLiveOnesNever() public {
        bytes32 live = keccak256("live");
        bytes32 r1 = keccak256("replay-1");
        bytes32 r2 = keccak256("replay-2");
        _anchor(live, false);
        _anchor(r1, true);
        _anchor(r2, true);
        vm.startPrank(ddma);
        pool.release(live, 1);
        pool.release(r1, 1);
        pool.release(r1, 2);
        vm.expectEmit(true, false, false, false, address(pool));
        emit ExerciseCooldownCleared(V);
        pool.clearExerciseCooldown(V);
        pool.release(r2, 1);
        pool.release(r2, 2);
        bytes32 live2 = keccak256("live-2");
        vm.stopPrank();
        _anchor(live2, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: village is in its cooldown"));
        pool.release(live2, 1); // the live cooldown is untouched
        vm.prank(thief);
        vm.expectRevert();
        pool.clearExerciseCooldown(V);
    }
}
