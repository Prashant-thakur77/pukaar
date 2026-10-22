// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {TestINR} from "../src/TestINR.sol";

contract TestINRTest is Test {
    TestINR internal token;
    address internal deployer = makeAddr("deployer");
    address internal donor = makeAddr("donor");

    function setUp() public {
        vm.prank(deployer);
        token = new TestINR();
    }

    function test_isNamedAsATestToken() public view {
        assertEq(token.name(), "Test INR (testnet only, no value)");
        assertEq(token.symbol(), "tINR");
        assertEq(token.decimals(), 18);
        assertEq(token.totalSupply(), 0);
    }

    function test_deployerMints() public {
        vm.prank(deployer);
        token.mint(donor, 1_500 ether);
        assertEq(token.balanceOf(donor), 1_500 ether);
    }

    function test_nobodyElseMints() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, donor, token.MINTER_ROLE())
        );
        vm.prank(donor);
        token.mint(donor, 1 ether);
    }

    function testFuzz_mintAddsExactly(uint128 a, uint128 b) public {
        vm.startPrank(deployer);
        token.mint(donor, a);
        token.mint(donor, b);
        vm.stopPrank();
        assertEq(token.balanceOf(donor), uint256(a) + uint256(b));
        assertEq(token.totalSupply(), uint256(a) + uint256(b));
    }
}
