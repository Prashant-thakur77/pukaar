// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";
import {ImpactAttestation} from "../src/ImpactAttestation.sol";

contract ImpactAttestationTest is Test {
    AlertRegistry internal registry;
    ImpactAttestation internal att;
    address internal admin = makeAddr("ddma-admin");
    address internal oracle = makeAddr("satellite-oracle");
    address internal officer = makeAddr("district-officer");
    address internal pradhan = makeAddr("pradhan-pandoh");
    address internal otherPradhan = makeAddr("pradhan-gohar");
    bytes32 internal constant PANDOH = keccak256("pandoh");
    bytes32 internal constant GOHAR = keccak256("gohar");
    bytes32 internal constant A1 = keccak256("alr_1");

    event Attested(bytes32 indexed alertId, ImpactAttestation.Attester who, address by, uint8 severity, bytes32 evidenceHash);
    event Confirmed(bytes32 indexed alertId);

    function setUp() public {
        vm.startPrank(admin);
        registry = new AlertRegistry(oracle);
        att = new ImpactAttestation(registry, oracle);
        att.grantRole(att.OFFICER_ROLE(), officer);
        att.grantRole(att.pradhanRole(PANDOH), pradhan);
        att.grantRole(att.pradhanRole(GOHAR), otherPradhan);
        vm.stopPrank();
        _anchor(A1, PANDOH);
    }

    function _anchor(bytes32 id, bytes32 village) internal {
        AlertRegistry.AlertRecord memory r;
        r.villageId = village;
        r.level = 2;
        r.capHash = keccak256(abi.encode(id));
        r.capUri = "u";
        r.issuedAt = 1;
        vm.prank(oracle);
        registry.anchorAlert(id, r);
    }

    function test_constructor() public {
        assertTrue(att.hasRole(att.ORACLE_ROLE(), oracle));
        assertTrue(att.hasRole(att.DEFAULT_ADMIN_ROLE(), admin));
        assertEq(address(att.registry()), address(registry));
        vm.expectRevert(bytes("ImpactAttestation: zero address"));
        new ImpactAttestation(AlertRegistry(address(0)), oracle);
        vm.expectRevert(bytes("ImpactAttestation: zero address"));
        new ImpactAttestation(registry, address(0));
    }

    function test_twoDistinctAttestersConfirm() public {
        vm.prank(officer);
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 2, keccak256("officer note"));
        assertFalse(att.isConfirmed(A1));
        vm.expectEmit(true, false, false, true, address(att));
        emit Attested(A1, ImpactAttestation.Attester.SATELLITE, oracle, 3, keccak256("diff.png"));
        vm.expectEmit(true, false, false, false, address(att));
        emit Confirmed(A1);
        vm.prank(oracle);
        att.attest(A1, ImpactAttestation.Attester.SATELLITE, 3, keccak256("diff.png"));
        assertTrue(att.isConfirmed(A1));
        assertEq(att.attesterCount(A1), 2);
        // the third one is recorded, Confirmed is not emitted again
        vm.prank(pradhan);
        att.attest(A1, ImpactAttestation.Attester.PRADHAN, 2, keccak256("photo"));
        assertEq(att.attesterCount(A1), 3);
        (address by, uint8 sev, bytes32 ev, uint64 at) = att.attestations(A1, ImpactAttestation.Attester.PRADHAN);
        assertEq(by, pradhan);
        assertEq(sev, 2);
        assertEq(ev, keccak256("photo"));
        assertEq(at, uint64(block.timestamp));
    }

    function test_sameAttesterTwiceIsNotTwo() public {
        vm.startPrank(officer);
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 3, keccak256("a"));
        vm.expectRevert(bytes("ImpactAttestation: already attested"));
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 3, keccak256("b"));
        vm.stopPrank();
        assertFalse(att.isConfirmed(A1));
    }

    function test_oneKeyHoldingTwoRolesCountsOnce() public {
        bytes32 role = att.pradhanRole(PANDOH);
        vm.prank(admin);
        att.grantRole(role, officer); // the officer's key also holds Pandoh's pradhan role
        vm.startPrank(officer);
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 3, keccak256("a"));
        att.attest(A1, ImpactAttestation.Attester.PRADHAN, 3, keccak256("b"));
        vm.stopPrank();
        assertFalse(att.isConfirmed(A1)); // two roles, one key: not two independent parties
        vm.prank(oracle);
        att.attest(A1, ImpactAttestation.Attester.SATELLITE, 2, keccak256("c"));
        assertTrue(att.isConfirmed(A1));
    }

    function test_lowSeverityDoesNotConfirm() public {
        vm.prank(officer);
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 1, keccak256("minor"));
        vm.prank(oracle);
        att.attest(A1, ImpactAttestation.Attester.SATELLITE, 0, keccak256("no water"));
        vm.prank(pradhan);
        att.attest(A1, ImpactAttestation.Attester.PRADHAN, 2, keccak256("photo"));
        assertFalse(att.isConfirmed(A1));
        assertEq(att.attesterCount(A1), 3);
    }

    function test_rolesAreEnforced() public {
        vm.prank(pradhan);
        vm.expectRevert(bytes("ImpactAttestation: not this attester"));
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 2, keccak256("x"));
        vm.prank(officer);
        vm.expectRevert(bytes("ImpactAttestation: not this attester"));
        att.attest(A1, ImpactAttestation.Attester.SATELLITE, 2, keccak256("x"));
        vm.prank(otherPradhan); // Gohar's pradhan, on a Pandoh alert
        vm.expectRevert(bytes("ImpactAttestation: not this attester"));
        att.attest(A1, ImpactAttestation.Attester.PRADHAN, 2, keccak256("x"));
    }

    function test_inputsAreChecked() public {
        vm.startPrank(officer);
        vm.expectRevert(bytes("ImpactAttestation: alert not anchored"));
        att.attest(keccak256("nope"), ImpactAttestation.Attester.OFFICER, 2, keccak256("x"));
        vm.expectRevert(bytes("ImpactAttestation: severity is 0 to 3"));
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 4, keccak256("x"));
        vm.expectRevert(bytes("ImpactAttestation: no evidence hash"));
        att.attest(A1, ImpactAttestation.Attester.OFFICER, 2, bytes32(0));
        vm.stopPrank();
    }

    function testFuzz_confirmedIffTwoDistinctSevere(uint8 s0, uint8 s1, uint8 s2) public {
        s0 = uint8(bound(s0, 0, 3));
        s1 = uint8(bound(s1, 0, 3));
        s2 = uint8(bound(s2, 0, 3));
        vm.prank(pradhan);
        att.attest(A1, ImpactAttestation.Attester.PRADHAN, s0, keccak256("p"));
        vm.prank(officer);
        att.attest(A1, ImpactAttestation.Attester.OFFICER, s1, keccak256("o"));
        vm.prank(oracle);
        att.attest(A1, ImpactAttestation.Attester.SATELLITE, s2, keccak256("s"));
        uint256 severe = (s0 >= 2 ? 1 : 0) + (s1 >= 2 ? 1 : 0) + (s2 >= 2 ? 1 : 0);
        assertEq(att.isConfirmed(A1), severe >= 2);
    }
}
