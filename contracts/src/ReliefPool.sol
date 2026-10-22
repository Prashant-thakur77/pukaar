// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {AlertRegistry} from "./AlertRegistry.sol";

interface IConfirmation {
    function isConfirmed(bytes32 alertId) external view returns (bool);
}

/// @title ReliefPool: the rule, the money, the receipts
/// @notice The DDMA writes the relief rule before the season and seals it; after sealRules() no amount or
///         threshold can change. A release names an alert anchored in the AlertRegistry and a tier: 1 is the
///         anticipatory tranche (the alert's level reached the rule's minimum; one per village per cooldown),
///         2 the confirmed-impact tranche (2 of 3 attesters, ImpactAttestation). The total, households x amount,
///         goes to the village's cash-out agent (pradhan or Business Correspondent), who records one receipt per
///         household with a Merkle proof of its salted hash. Ids, amounts and hashes only: nothing personal.
///         After the seal, a village's household list and cash-out agent can still change (people register), but
///         only after a public delay of one cooldown, so neither can be moved just before a release.
contract ReliefPool is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant DDMA_ROLE = keccak256("DDMA_ROLE");
    uint8 public constant TIER_ANTICIPATORY = 1;
    uint8 public constant TIER_CONFIRMED = 2;

    struct Rule {
        uint8 minLevelAnticipatory; // 2 = warning
        uint256 amountAnticipatory; // per household, token wei
        uint256 amountConfirmed; // per household, on 2-of-3 confirmation
        uint32 cooldownHours; // one anticipatory payout per village per cooldown
    }

    IERC20 public immutable token;
    AlertRegistry public immutable registry;
    IConfirmation public immutable confirmation; // ImpactAttestation; zero until it is deployed: no tier 2
    bool public immutable allowExercisePayout; // testnet demo only: production deploys pass false

    Rule public rule;
    bool public rulesSealed;
    uint64 public sealedAt;
    mapping(bytes32 villageId => bytes32) public households; // Merkle root of salted household hashes
    mapping(bytes32 villageId => uint32) public householdCount;
    mapping(bytes32 villageId => address) public cashOutAgent;
    mapping(bytes32 alertId => mapping(uint8 tier => bool)) public released;
    mapping(bytes32 villageId => mapping(bool exercise => uint64)) public lastAnticipatory;
    mapping(bytes32 villageId => mapping(bool exercise => uint64)) public lastConfirmed;

    struct PendingHouseholds {
        bytes32 root;
        uint32 count;
        uint64 effectiveAt;
    }

    struct PendingAgent {
        address agent;
        uint64 effectiveAt;
    }

    mapping(bytes32 villageId => PendingHouseholds) public pendingHouseholds;
    mapping(bytes32 villageId => PendingAgent) public pendingAgent;
    mapping(bytes32 alertId => mapping(bytes32 household => bool)) public receipted;
    mapping(bytes32 alertId => uint32) public receiptCount;

    event Funded(address indexed donor, uint256 amount);
    event RuleSet(uint8 minLevelAnticipatory, uint256 amountAnticipatory, uint256 amountConfirmed, uint32 cooldownHours);
    event RulesSealed(uint64 at);
    event HouseholdsSet(bytes32 indexed villageId, bytes32 root, uint32 count);
    event CashOutAgentSet(bytes32 indexed villageId, address agent);
    event HouseholdsScheduled(bytes32 indexed villageId, bytes32 root, uint32 count, uint64 effectiveAt);
    event CashOutAgentScheduled(bytes32 indexed villageId, address agent, uint64 effectiveAt);
    event ExerciseCooldownCleared(bytes32 indexed villageId);
    event Released(
        bytes32 indexed alertId, bytes32 indexed villageId, uint8 tier, uint32 households, uint256 total, bool exercise
    );
    event PayoutReceipt(bytes32 indexed alertId, bytes32 indexed householdHash, bytes32 upiRefHash);

    constructor(IERC20 token_, AlertRegistry registry_, IConfirmation confirmation_, bool allowExercisePayout_, address ddma) {
        require(address(token_) != address(0) && address(registry_) != address(0), "ReliefPool: zero address");
        require(ddma != address(0), "ReliefPool: zero address");
        token = token_;
        registry = registry_;
        confirmation = confirmation_;
        allowExercisePayout = allowExercisePayout_;
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(DDMA_ROLE, ddma);
    }

    function setRule(Rule calldata r) external onlyRole(DDMA_ROLE) {
        require(!rulesSealed, "ReliefPool: rules are sealed for the season");
        require(r.minLevelAnticipatory >= 1 && r.minLevelAnticipatory <= 3, "ReliefPool: level must be 1 to 3");
        require(r.amountAnticipatory > 0 && r.amountConfirmed > 0, "ReliefPool: amounts must be above zero");
        require(r.cooldownHours > 0, "ReliefPool: cooldown must be above zero");
        rule = r;
        emit RuleSet(r.minLevelAnticipatory, r.amountAnticipatory, r.amountConfirmed, r.cooldownHours);
    }

    function sealRules() external onlyRole(DDMA_ROLE) {
        require(!rulesSealed, "ReliefPool: rules are sealed for the season");
        require(rule.amountAnticipatory > 0, "ReliefPool: no rule to seal");
        rulesSealed = true;
        sealedAt = uint64(block.timestamp);
        emit RulesSealed(sealedAt);
    }

    function setHouseholds(bytes32 villageId, bytes32 root, uint32 count) external onlyRole(DDMA_ROLE) {
        require(villageId != bytes32(0), "ReliefPool: no village");
        require((root == bytes32(0)) == (count == 0), "ReliefPool: root and count disagree");
        if (!rulesSealed) {
            households[villageId] = root;
            householdCount[villageId] = count;
            emit HouseholdsSet(villageId, root, count);
            return;
        }
        uint64 at = uint64(block.timestamp + uint256(rule.cooldownHours) * 1 hours);
        pendingHouseholds[villageId] = PendingHouseholds(root, count, at);
        emit HouseholdsScheduled(villageId, root, count, at);
    }

    function setCashOutAgent(bytes32 villageId, address agent) external onlyRole(DDMA_ROLE) {
        require(villageId != bytes32(0) && agent != address(0), "ReliefPool: zero address");
        if (!rulesSealed) {
            cashOutAgent[villageId] = agent;
            emit CashOutAgentSet(villageId, agent);
            return;
        }
        uint64 at = uint64(block.timestamp + uint256(rule.cooldownHours) * 1 hours);
        pendingAgent[villageId] = PendingAgent(agent, at);
        emit CashOutAgentScheduled(villageId, agent, at);
    }

    /// Apply a village's scheduled household list or agent once its delay has passed (anyone may call it;
    /// release and receipt call it too).
    function applyDue(bytes32 villageId) public {
        PendingHouseholds memory h = pendingHouseholds[villageId];
        if (h.effectiveAt != 0 && block.timestamp >= h.effectiveAt) {
            households[villageId] = h.root;
            householdCount[villageId] = h.count;
            delete pendingHouseholds[villageId];
            emit HouseholdsSet(villageId, h.root, h.count);
        }
        PendingAgent memory g = pendingAgent[villageId];
        if (g.effectiveAt != 0 && block.timestamp >= g.effectiveAt) {
            cashOutAgent[villageId] = g.agent;
            delete pendingAgent[villageId];
            emit CashOutAgentSet(villageId, g.agent);
        }
    }

    /// Replays and drills are run again (a demo, a training): their cooldowns may be cleared. Live ones never are.
    function clearExerciseCooldown(bytes32 villageId) external onlyRole(DDMA_ROLE) {
        lastAnticipatory[villageId][true] = 0;
        lastConfirmed[villageId][true] = 0;
        emit ExerciseCooldownCleared(villageId);
    }

    /// Anyone may fund the pool (a donor approves the token first).
    function fund(uint256 amount) external {
        require(amount > 0, "ReliefPool: nothing to fund");
        token.safeTransferFrom(msg.sender, address(this), amount);
        emit Funded(msg.sender, amount);
    }

    function release(bytes32 alertId, uint8 tier) external onlyRole(DDMA_ROLE) nonReentrant {
        require(rulesSealed, "ReliefPool: rules are not sealed yet");
        require(registry.exists(alertId), "ReliefPool: alert not anchored");
        require(!released[alertId][tier], "ReliefPool: already released for this alert and tier");
        bytes32 village = registry.villageOf(alertId);
        bool exercise = registry.isExercise(alertId);
        require(!exercise || allowExercisePayout, "ReliefPool: exercises do not pay out on this deployment");
        applyDue(village);
        uint256 amount;
        if (tier == TIER_ANTICIPATORY) {
            require(registry.levelOf(alertId) >= rule.minLevelAnticipatory, "ReliefPool: level below the rule");
            uint64 last = lastAnticipatory[village][exercise];
            require(
                last == 0 || block.timestamp >= uint256(last) + uint256(rule.cooldownHours) * 1 hours,
                "ReliefPool: village is in its cooldown"
            );
            lastAnticipatory[village][exercise] = uint64(block.timestamp);
            amount = rule.amountAnticipatory;
        } else if (tier == TIER_CONFIRMED) {
            require(address(confirmation) != address(0), "ReliefPool: no attestation contract");
            require(confirmation.isConfirmed(alertId), "ReliefPool: impact not confirmed by 2 of 3");
            uint64 lastC = lastConfirmed[village][exercise];
            require(
                lastC == 0 || block.timestamp >= uint256(lastC) + uint256(rule.cooldownHours) * 1 hours,
                "ReliefPool: village is in its cooldown"
            );
            lastConfirmed[village][exercise] = uint64(block.timestamp);
            amount = rule.amountConfirmed;
        } else {
            revert("ReliefPool: tier must be 1 or 2");
        }
        uint32 n = householdCount[village];
        address agent = cashOutAgent[village];
        require(n > 0, "ReliefPool: village has no households");
        require(agent != address(0), "ReliefPool: village has no cash-out agent");
        uint256 total = amount * n;
        require(token.balanceOf(address(this)) >= total, "ReliefPool: pool too small for this release");
        released[alertId][tier] = true;
        token.safeTransfer(agent, total);
        emit Released(alertId, village, tier, n, total, exercise);
    }

    /// The village's cash-out agent records that one household was paid, with a hash of the UPI or cash reference.
    function receipt(bytes32 alertId, bytes32 householdHash, bytes32[] calldata proof, bytes32 upiRefHash) external {
        bytes32 village = registry.villageOf(alertId);
        applyDue(village);
        require(msg.sender == cashOutAgent[village] && msg.sender != address(0), "ReliefPool: only the village's cash-out agent");
        require(
            released[alertId][TIER_ANTICIPATORY] || released[alertId][TIER_CONFIRMED], "ReliefPool: nothing released for this alert"
        );
        require(upiRefHash != bytes32(0), "ReliefPool: no payment reference");
        require(!receipted[alertId][householdHash], "ReliefPool: household already has a receipt for this alert");
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(householdHash))));
        require(MerkleProof.verify(proof, households[village], leaf), "ReliefPool: household not in this village");
        receipted[alertId][householdHash] = true;
        receiptCount[alertId] += 1;
        emit PayoutReceipt(alertId, householdHash, upiRefHash);
    }
}
