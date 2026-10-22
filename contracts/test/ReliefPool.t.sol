// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {AlertRegistry} from "../src/AlertRegistry.sol";
import {ReliefPool, IConfirmation} from "../src/ReliefPool.sol";
import {TestINR} from "../src/TestINR.sol";

contract FakeConfirmation is IConfirmation {
    mapping(bytes32 => bool) public confirmed;

    function set(bytes32 id, bool v) external {
        confirmed[id] = v;
    }

    function isConfirmed(bytes32 id) external view returns (bool) {
        return confirmed[id];
    }
}

/// A hostile token: on transfer it calls back into release() to try to pay twice.
contract ReentrantToken is ERC20 {
    ReliefPool public pool;
    bytes32 public alertId;

    constructor() ERC20("Evil", "EVIL") {}

    function arm(ReliefPool p, bytes32 id) external {
        pool = p;
        alertId = id;
    }

    function mint(address to, uint256 a) external {
        _mint(to, a);
    }

    function transfer(address to, uint256 a) public override returns (bool) {
        if (address(pool) != address(0)) pool.release(alertId, 2);
        return super.transfer(to, a);
    }
}

contract ReliefPoolTest is Test {
    using stdJson for string;

    TestINR internal token;
    AlertRegistry internal registry;
    FakeConfirmation internal confirmation;
    ReliefPool internal pool;
    address internal deployer = makeAddr("deployer");
    address internal oracle = makeAddr("oracle");
    address internal ddma = makeAddr("ddma");
    address internal agent = makeAddr("pradhan-sujanpur");
    address internal donor = makeAddr("donor");
    address internal stranger = makeAddr("stranger");

    string internal fx;
    bytes32 internal sujanpur;
    bytes32 internal constant GOHAR = keccak256("gohar");
    bytes32 internal constant A1 = keccak256("alr_1");
    bytes32 internal constant A2 = keccak256("alr_2");
    uint256 internal constant ANTICIPATORY = 1_500 ether;
    uint256 internal constant CONFIRMED = 4_000 ether;

    event Released(bytes32 indexed alertId, bytes32 indexed villageId, uint8 tier, uint32 households, uint256 total, bool exercise);
    event PayoutReceipt(bytes32 indexed alertId, bytes32 indexed householdHash, bytes32 upiRefHash);
    event Funded(address indexed donor, uint256 amount);

    function setUp() public {
        fx = vm.readFile(string.concat(vm.projectRoot(), "/test/fixtures/households.json"));
        sujanpur = fx.readBytes32(".village_key");
        vm.startPrank(deployer);
        token = new TestINR();
        registry = new AlertRegistry(oracle);
        confirmation = new FakeConfirmation();
        pool = new ReliefPool(IERC20(address(token)), registry, confirmation, true, ddma);
        token.mint(address(pool), 1_000_000 ether);
        vm.stopPrank();
    }

    // -- helpers ---------------------------------------------------------------------------------------
    function _rule() internal pure returns (ReliefPool.Rule memory) {
        return ReliefPool.Rule({minLevelAnticipatory: 2, amountAnticipatory: ANTICIPATORY, amountConfirmed: CONFIRMED, cooldownHours: 72});
    }

    function _ready() internal {
        vm.startPrank(ddma);
        pool.setRule(_rule());
        pool.sealRules();
        pool.setHouseholds(sujanpur, fx.readBytes32(".root"), uint32(fx.readUint(".count")));
        pool.setCashOutAgent(sujanpur, agent);
        vm.stopPrank();
    }

    function _anchor(bytes32 id, bytes32 village, uint8 level, bool exercise) internal {
        AlertRegistry.AlertRecord memory r;
        r.villageId = village;
        r.level = level;
        r.capHash = keccak256(abi.encode(id));
        r.capUri = "https://api.example/cap/alerts/x.xml";
        r.issuedAt = uint64(block.timestamp);
        r.exercise = exercise;
        vm.prank(oracle);
        registry.anchorAlert(id, r);
    }

    function _household(uint256 i) internal view returns (bytes32 h, bytes32[] memory proof) {
        string memory k = string.concat(".households[", vm.toString(i), "]");
        h = fx.readBytes32(string.concat(k, ".hash"));
        proof = fx.readBytes32Array(string.concat(k, ".proof"));
    }

    // -- roles and the rule ------------------------------------------------------------------------------
    function test_rolesAndConstructor() public {
        assertTrue(pool.hasRole(pool.DDMA_ROLE(), ddma));
        assertTrue(pool.hasRole(pool.DEFAULT_ADMIN_ROLE(), deployer));
        assertFalse(pool.hasRole(pool.DDMA_ROLE(), deployer));
        assertTrue(pool.allowExercisePayout());
        vm.expectRevert(bytes("ReliefPool: zero address"));
        new ReliefPool(IERC20(address(0)), registry, confirmation, true, ddma);
        vm.expectRevert(bytes("ReliefPool: zero address"));
        new ReliefPool(IERC20(address(token)), registry, confirmation, true, address(0));
    }

    function test_onlyDdmaWritesTheRule() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, stranger, pool.DDMA_ROLE())
        );
        vm.prank(stranger);
        pool.setRule(_rule());
    }

    function test_ruleIsCheckedThenSealedForTheSeason() public {
        vm.startPrank(ddma);
        vm.expectRevert(bytes("ReliefPool: no rule to seal"));
        pool.sealRules();

        ReliefPool.Rule memory r = _rule();
        r.minLevelAnticipatory = 0;
        vm.expectRevert(bytes("ReliefPool: level must be 1 to 3"));
        pool.setRule(r);
        r = _rule();
        r.minLevelAnticipatory = 4;
        vm.expectRevert(bytes("ReliefPool: level must be 1 to 3"));
        pool.setRule(r);
        r = _rule();
        r.amountConfirmed = 0;
        vm.expectRevert(bytes("ReliefPool: amounts must be above zero"));
        pool.setRule(r);
        r = _rule();
        r.cooldownHours = 0;
        vm.expectRevert(bytes("ReliefPool: cooldown must be above zero"));
        pool.setRule(r);

        pool.setRule(_rule());
        vm.warp(1_000_000);
        pool.sealRules();
        assertTrue(pool.rulesSealed());
        assertEq(pool.sealedAt(), 1_000_000);

        ReliefPool.Rule memory higher = _rule();
        higher.amountAnticipatory = 99_999 ether;
        vm.expectRevert(bytes("ReliefPool: rules are sealed for the season"));
        pool.setRule(higher);
        vm.expectRevert(bytes("ReliefPool: rules are sealed for the season"));
        pool.sealRules();
        vm.stopPrank();
        (, uint256 a,,) = pool.rule();
        assertEq(a, ANTICIPATORY);
    }

    function test_householdsAndAgentSetup() public {
        vm.startPrank(ddma);
        vm.expectRevert(bytes("ReliefPool: no village"));
        pool.setHouseholds(bytes32(0), bytes32(uint256(1)), 1);
        vm.expectRevert(bytes("ReliefPool: root and count disagree"));
        pool.setHouseholds(sujanpur, bytes32(0), 3);
        vm.expectRevert(bytes("ReliefPool: root and count disagree"));
        pool.setHouseholds(sujanpur, bytes32(uint256(1)), 0);
        vm.expectRevert(bytes("ReliefPool: zero address"));
        pool.setCashOutAgent(sujanpur, address(0));
        vm.stopPrank();
    }

    // -- funding -----------------------------------------------------------------------------------------
    function test_anyoneFunds() public {
        vm.prank(deployer);
        token.mint(donor, 10 ether);
        vm.startPrank(donor);
        token.approve(address(pool), 10 ether);
        vm.expectEmit(true, false, false, true, address(pool));
        emit Funded(donor, 10 ether);
        pool.fund(10 ether);
        vm.expectRevert(bytes("ReliefPool: nothing to fund"));
        pool.fund(0);
        vm.stopPrank();
        assertEq(token.balanceOf(address(pool)), 1_000_010 ether);
    }

    // -- tier 1, anticipatory ----------------------------------------------------------------------------
    function test_anticipatoryReleasePaysTheAgentHouseholdsTimesAmount() public {
        _ready();
        _anchor(A1, sujanpur, 2, true);
        vm.expectEmit(true, true, false, true, address(pool));
        emit Released(A1, sujanpur, 1, 5, 5 * ANTICIPATORY, true);
        vm.prank(ddma);
        pool.release(A1, 1);
        assertEq(token.balanceOf(agent), 5 * ANTICIPATORY);
        assertTrue(pool.released(A1, 1));
    }

    function test_releaseNeedsSealedRulesAnAnchorAndTheDdma() public {
        _anchor(A1, sujanpur, 2, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: rules are not sealed yet"));
        pool.release(A1, 1);
        _ready();
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: alert not anchored"));
        pool.release(A2, 1);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, agent, pool.DDMA_ROLE())
        );
        vm.prank(agent);
        pool.release(A1, 1);
    }

    function test_eachTierOncePerAlert() public {
        _ready();
        _anchor(A1, sujanpur, 3, false);
        vm.startPrank(ddma);
        pool.release(A1, 1);
        vm.warp(block.timestamp + 100 days);
        vm.expectRevert(bytes("ReliefPool: already released for this alert and tier"));
        pool.release(A1, 1);
        vm.stopPrank();
    }

    function test_levelBelowTheRuleIsRefused() public {
        _ready();
        _anchor(A1, sujanpur, 1, false); // watch
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: level below the rule"));
        pool.release(A1, 1);
    }

    function test_cooldownPerVillageAndSeparateForExercises() public {
        _ready();
        vm.warp(10 days);
        _anchor(A1, sujanpur, 2, false);
        _anchor(A2, sujanpur, 3, false);
        bytes32 replay = keccak256("alr_replay");
        _anchor(replay, sujanpur, 2, true);
        vm.startPrank(ddma);
        pool.release(A1, 1);
        vm.warp(block.timestamp + 71 hours);
        vm.expectRevert(bytes("ReliefPool: village is in its cooldown"));
        pool.release(A2, 1);
        pool.release(replay, 1); // a demo replay never blocks, nor is blocked by, a live payout
        vm.warp(block.timestamp + 1 hours);
        pool.release(A2, 1);
        vm.stopPrank();
        assertEq(token.balanceOf(agent), 3 * 5 * ANTICIPATORY);
    }

    function test_productionDeploymentRefusesExercisePayouts() public {
        vm.prank(deployer);
        ReliefPool prod = new ReliefPool(IERC20(address(token)), registry, confirmation, false, ddma);
        vm.startPrank(ddma);
        prod.setRule(_rule());
        prod.sealRules();
        prod.setHouseholds(sujanpur, fx.readBytes32(".root"), 5);
        prod.setCashOutAgent(sujanpur, agent);
        vm.stopPrank();
        _anchor(A1, sujanpur, 3, true);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: exercises do not pay out on this deployment"));
        prod.release(A1, 1);
    }

    function test_villageMustHaveHouseholdsAnAgentAndEnoughMoney() public {
        _ready();
        _anchor(A1, GOHAR, 2, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: village has no households"));
        pool.release(A1, 1);

        vm.prank(ddma);
        pool.setHouseholds(GOHAR, bytes32(uint256(1)), 1);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: village has no cash-out agent"));
        pool.release(A1, 1);

        vm.startPrank(ddma);
        pool.setCashOutAgent(GOHAR, agent);
        pool.setHouseholds(GOHAR, bytes32(uint256(1)), 1_000);
        vm.expectRevert(bytes("ReliefPool: pool too small for this release"));
        pool.release(A1, 1);
        vm.stopPrank();
        assertFalse(pool.released(A1, 1));
    }

    function test_unknownTierIsRefused() public {
        _ready();
        _anchor(A1, sujanpur, 2, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: tier must be 1 or 2"));
        pool.release(A1, 3);
    }

    // -- tier 2, confirmed impact ------------------------------------------------------------------------
    function test_confirmedTierNeedsTheAttestation() public {
        _ready();
        _anchor(A1, sujanpur, 3, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: impact not confirmed by 2 of 3"));
        pool.release(A1, 2);
        confirmation.set(A1, true);
        vm.prank(ddma);
        pool.release(A1, 2);
        assertEq(token.balanceOf(agent), 5 * CONFIRMED);
    }

    function test_noAttestationContractMeansNoTier2() public {
        vm.prank(deployer);
        ReliefPool early = new ReliefPool(IERC20(address(token)), registry, IConfirmation(address(0)), true, ddma);
        vm.startPrank(ddma);
        early.setRule(_rule());
        early.sealRules();
        vm.stopPrank();
        _anchor(A1, sujanpur, 3, false);
        vm.prank(ddma);
        vm.expectRevert(bytes("ReliefPool: no attestation contract"));
        early.release(A1, 2);
    }

    function test_reentrancyIsBlocked() public {
        vm.startPrank(deployer);
        ReentrantToken evil = new ReentrantToken();
        ReliefPool p = new ReliefPool(IERC20(address(evil)), registry, confirmation, true, ddma);
        evil.mint(address(p), 1_000_000 ether);
        vm.stopPrank();
        vm.startPrank(ddma);
        p.setRule(_rule());
        p.sealRules();
        p.setHouseholds(sujanpur, fx.readBytes32(".root"), 5);
        p.setCashOutAgent(sujanpur, agent);
        vm.stopPrank();
        bytes32 role = p.DDMA_ROLE();
        vm.prank(deployer);
        p.grantRole(role, address(evil)); // even holding the role, it cannot re-enter
        _anchor(A1, sujanpur, 3, false);
        confirmation.set(A1, true);
        evil.arm(p, A1);
        vm.prank(ddma);
        vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
        p.release(A1, 1);
    }

    // -- receipts (Merkle proofs built by backend/src/Pukaar/raahat/households.py) -----------------------
    function test_agentRecordsAReceiptPerHousehold() public {
        _ready();
        _anchor(A1, sujanpur, 2, false);
        vm.prank(ddma);
        pool.release(A1, 1);
        for (uint256 i = 0; i < 5; i++) {
            (bytes32 h, bytes32[] memory proof) = _household(i);
            bytes32 upi = keccak256(abi.encode("UPI-REF", i));
            vm.expectEmit(true, true, false, true, address(pool));
            emit PayoutReceipt(A1, h, upi);
            vm.prank(agent);
            pool.receipt(A1, h, proof, upi);
        }
        assertEq(pool.receiptCount(A1), 5);
    }

    function test_receiptReplayedIsRefused() public {
        _ready();
        _anchor(A1, sujanpur, 2, false);
        vm.prank(ddma);
        pool.release(A1, 1);
        (bytes32 h, bytes32[] memory proof) = _household(2);
        vm.startPrank(agent);
        pool.receipt(A1, h, proof, keccak256("UPI-1"));
        vm.expectRevert(bytes("ReliefPool: household already has a receipt for this alert"));
        pool.receipt(A1, h, proof, keccak256("UPI-2"));
        vm.stopPrank();
    }

    function test_receiptForAHouseholdOfAnotherVillageIsRefused() public {
        _ready();
        _anchor(A1, sujanpur, 2, false);
        vm.prank(ddma);
        pool.release(A1, 1);
        bytes32 h = fx.readBytes32(".stranger.hash");
        bytes32[] memory proof = fx.readBytes32Array(".stranger.proof");
        vm.prank(agent);
        vm.expectRevert(bytes("ReliefPool: household not in this village"));
        pool.receipt(A1, h, proof, keccak256("UPI"));
    }

    function test_receiptOnlyByTheAgentAfterARelease() public {
        _ready();
        _anchor(A1, sujanpur, 2, false);
        (bytes32 h, bytes32[] memory proof) = _household(0);
        vm.prank(agent);
        vm.expectRevert(bytes("ReliefPool: nothing released for this alert"));
        pool.receipt(A1, h, proof, keccak256("UPI"));
        vm.prank(ddma);
        pool.release(A1, 1);
        vm.prank(stranger);
        vm.expectRevert(bytes("ReliefPool: only the village's cash-out agent"));
        pool.receipt(A1, h, proof, keccak256("UPI"));
        vm.prank(agent);
        vm.expectRevert(bytes("ReliefPool: no payment reference"));
        pool.receipt(A1, h, proof, bytes32(0));
    }

    // -- fuzz --------------------------------------------------------------------------------------------
    function testFuzz_releasePaysExactlyHouseholdsTimesAmount(uint96 anticipatory, uint96 confirmed, uint16 n) public {
        anticipatory = uint96(bound(anticipatory, 1, 1e24));
        confirmed = uint96(bound(confirmed, 1, 1e24));
        n = uint16(bound(n, 1, 5_000));
        vm.startPrank(ddma);
        pool.setRule(ReliefPool.Rule(2, anticipatory, confirmed, 72));
        pool.sealRules();
        pool.setHouseholds(sujanpur, bytes32(uint256(1)), n);
        pool.setCashOutAgent(sujanpur, agent);
        vm.stopPrank();
        vm.prank(deployer);
        token.mint(address(pool), uint256(n) * (uint256(anticipatory) + uint256(confirmed)));
        uint256 before = token.balanceOf(address(pool));
        _anchor(A1, sujanpur, 2, false);
        confirmation.set(A1, true);
        vm.startPrank(ddma);
        pool.release(A1, 1);
        pool.release(A1, 2);
        vm.stopPrank();
        uint256 paid = uint256(n) * (uint256(anticipatory) + uint256(confirmed));
        assertEq(token.balanceOf(agent), paid);
        assertEq(token.balanceOf(address(pool)), before - paid);
    }
}
