// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";

contract AlertRegistryTest is Test {
    AlertRegistry internal reg;
    address internal admin = makeAddr("ddma-admin");
    address internal oracle = makeAddr("pukaar-workflow");
    address internal stranger = makeAddr("stranger");
    bytes32 internal constant ID = keccak256("01J9ALERT");
    bytes32 internal constant GOHAR = keccak256("gohar");

    event AlertAnchored(bytes32 indexed alertId, bytes32 indexed villageId, uint8 level, bool exercise, bytes32 capHash);
    event OutcomeAnchored(bytes32 indexed alertId, uint32 delivered, uint32 acknowledged, bytes32 afterActionHash);

    function setUp() public {
        vm.prank(admin);
        reg = new AlertRegistry(oracle);
    }

    function _record(uint8 level, bool exercise) internal view returns (AlertRegistry.AlertRecord memory r) {
        r.villageId = GOHAR;
        r.level = level;
        r.capHash = keccak256("<alert>cap</alert>");
        r.capUri = "https://api.example/cap/alerts/01J9ALERT.xml";
        r.issuedAt = uint64(block.timestamp);
        r.exercise = exercise;
    }

    function test_rolesAtDeploy() public view {
        assertTrue(reg.hasRole(reg.DEFAULT_ADMIN_ROLE(), admin));
        assertTrue(reg.hasRole(reg.ORACLE_ROLE(), oracle));
        assertFalse(reg.hasRole(reg.ORACLE_ROLE(), admin));
    }

    function test_constructorRefusesZeroOracle() public {
        vm.expectRevert(bytes("AlertRegistry: oracle is the zero address"));
        new AlertRegistry(address(0));
    }

    function test_anchorStoresAndEmits() public {
        AlertRegistry.AlertRecord memory r = _record(2, true);
        vm.expectEmit(true, true, false, true, address(reg));
        emit AlertAnchored(ID, GOHAR, 2, true, r.capHash);
        vm.prank(oracle);
        reg.anchorAlert(ID, r);

        AlertRegistry.AlertRecord memory got = reg.get(ID);
        assertEq(got.villageId, GOHAR);
        assertEq(got.level, 2);
        assertEq(got.capHash, r.capHash);
        assertEq(got.capUri, r.capUri);
        assertEq(got.issuedAt, r.issuedAt);
        assertTrue(got.exercise);
        assertTrue(reg.exists(ID));
        assertEq(reg.levelOf(ID), 2);
        assertEq(reg.villageOf(ID), GOHAR);
        assertTrue(reg.isExercise(ID));
        assertFalse(reg.exists(keccak256("other")));
    }

    function test_onlyOracleAnchors() public {
        AlertRegistry.AlertRecord memory r = _record(2, false);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, stranger, reg.ORACLE_ROLE())
        );
        vm.prank(stranger);
        reg.anchorAlert(ID, r);
    }

    function test_anchorIsWriteOnce() public {
        vm.startPrank(oracle);
        reg.anchorAlert(ID, _record(2, false));
        AlertRegistry.AlertRecord memory later = _record(3, false);
        later.capHash = keccak256("back-dated");
        vm.expectRevert(bytes("AlertRegistry: alert already anchored"));
        reg.anchorAlert(ID, later);
        vm.stopPrank();
        assertEq(reg.get(ID).level, 2);
    }

    function test_anchorChecksTheRecord() public {
        vm.startPrank(oracle);
        AlertRegistry.AlertRecord memory r = _record(2, false);
        vm.expectRevert(bytes("AlertRegistry: empty alert id"));
        reg.anchorAlert(bytes32(0), r);

        r = _record(0, false);
        vm.expectRevert(bytes("AlertRegistry: level must be 1 (watch), 2 (warning) or 3 (critical)"));
        reg.anchorAlert(ID, r);
        r = _record(4, false);
        vm.expectRevert(bytes("AlertRegistry: level must be 1 (watch), 2 (warning) or 3 (critical)"));
        reg.anchorAlert(ID, r);

        r = _record(2, false);
        r.capHash = bytes32(0);
        vm.expectRevert(bytes("AlertRegistry: no CAP hash"));
        reg.anchorAlert(ID, r);

        r = _record(2, false);
        r.villageId = bytes32(0);
        vm.expectRevert(bytes("AlertRegistry: no village"));
        reg.anchorAlert(ID, r);

        r = _record(2, false);
        r.issuedAt = 0;
        vm.expectRevert(bytes("AlertRegistry: no issue time"));
        reg.anchorAlert(ID, r);

        r = _record(2, false);
        r.delivered = 5;
        vm.expectRevert(bytes("AlertRegistry: the outcome is anchored at close, not with the alert"));
        reg.anchorAlert(ID, r);
        vm.stopPrank();
    }

    function test_outcomeOnceAfterAnchor() public {
        bytes32 report = keccak256("after-action.html");
        vm.startPrank(oracle);
        vm.expectRevert(bytes("AlertRegistry: alert not anchored"));
        reg.anchorOutcome(ID, 10, 7, report);

        reg.anchorAlert(ID, _record(3, false));
        vm.expectEmit(true, false, false, true, address(reg));
        emit OutcomeAnchored(ID, 10, 7, report);
        reg.anchorOutcome(ID, 10, 7, report);

        vm.expectRevert(bytes("AlertRegistry: outcome already anchored"));
        reg.anchorOutcome(ID, 99, 99, keccak256("rewritten"));
        vm.stopPrank();

        AlertRegistry.AlertRecord memory got = reg.get(ID);
        assertEq(got.delivered, 10);
        assertEq(got.acknowledged, 7);
        assertEq(got.afterActionHash, report);
        assertTrue(reg.outcomeAnchored(ID));
    }

    function test_outcomeWithNoReportIsStillOnce() public {
        vm.startPrank(oracle);
        reg.anchorAlert(ID, _record(2, false));
        reg.anchorOutcome(ID, 0, 0, bytes32(0)); // nobody reached, report failed: still a record, once
        vm.expectRevert(bytes("AlertRegistry: outcome already anchored"));
        reg.anchorOutcome(ID, 1, 1, keccak256("x"));
        vm.stopPrank();
    }

    function test_onlyOracleAnchorsOutcome() public {
        vm.prank(oracle);
        reg.anchorAlert(ID, _record(2, false));
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, reg.ORACLE_ROLE())
        );
        vm.prank(admin);
        reg.anchorOutcome(ID, 1, 1, bytes32(0));
    }

    function test_exerciseFlagIsKeptAsAnchored() public {
        vm.startPrank(oracle);
        reg.anchorAlert(ID, _record(2, true));
        reg.anchorAlert(keccak256("live"), _record(2, false));
        vm.stopPrank();
        assertTrue(reg.isExercise(ID));
        assertFalse(reg.isExercise(keccak256("live")));
    }

    function testFuzz_anchorAnyValidLevelAndCounts(bytes32 id, uint8 level, uint32 delivered, uint32 acked) public {
        vm.assume(id != bytes32(0));
        level = uint8(bound(level, 1, 3));
        vm.startPrank(oracle);
        reg.anchorAlert(id, _record(level, false));
        reg.anchorOutcome(id, delivered, acked, keccak256(abi.encode(id)));
        vm.stopPrank();
        assertEq(reg.levelOf(id), level);
        assertEq(reg.get(id).delivered, delivered);
        assertEq(reg.get(id).acknowledged, acked);
    }
}
