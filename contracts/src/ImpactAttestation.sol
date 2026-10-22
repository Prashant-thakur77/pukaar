// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {AlertRegistry} from "./AlertRegistry.sol";
import {IConfirmation} from "./ReliefPool.sol";

/// @title ImpactAttestation: 2-of-3 confirmation that the flood happened
/// @notice Three independent attesters can each say once, per anchored alert, how bad the flood was (severity 0 none
///         seen, 1 minor, 2 damaging, 3 severe) with the hash of their evidence: the village's pradhan (a photo report;
///         role pradhanRole(villageId)), a district officer (OFFICER_ROLE) and the satellite oracle (ORACLE_ROLE, a
///         Sentinel-2 before/after water diff). The alert is confirmed when two different keys say severity >= 2:
///         one key holding two roles counts once, so no single party can confirm alone. The evidence stays off chain;
///         its hash is public. ReliefPool asks isConfirmed() before the confirmed tranche.
contract ImpactAttestation is AccessControl, IConfirmation {
    bytes32 public constant OFFICER_ROLE = keccak256("OFFICER_ROLE");
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    uint8 public constant CONFIRMING_SEVERITY = 2;

    enum Attester {
        PRADHAN,
        OFFICER,
        SATELLITE
    }

    struct Attestation {
        address by;
        uint8 severity;
        bytes32 evidenceHash;
        uint64 at;
    }

    AlertRegistry public immutable registry;
    mapping(bytes32 alertId => mapping(Attester => Attestation)) public attestations;
    mapping(bytes32 alertId => uint8) public attesterCount;
    mapping(bytes32 alertId => bool) public confirmedEmitted;

    event Attested(bytes32 indexed alertId, Attester who, address by, uint8 severity, bytes32 evidenceHash);
    event Confirmed(bytes32 indexed alertId);

    constructor(AlertRegistry registry_, address oracle) {
        require(address(registry_) != address(0) && oracle != address(0), "ImpactAttestation: zero address");
        registry = registry_;
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(ORACLE_ROLE, oracle);
    }

    /// The role a village's pradhan holds: one per village, so a pradhan attests for their own village only.
    function pradhanRole(bytes32 villageId) public pure returns (bytes32) {
        return keccak256(abi.encode(villageId, "pradhan"));
    }

    function attest(bytes32 alertId, Attester who, uint8 severity, bytes32 evidenceHash) external {
        require(registry.exists(alertId), "ImpactAttestation: alert not anchored");
        require(severity <= 3, "ImpactAttestation: severity is 0 to 3");
        require(evidenceHash != bytes32(0), "ImpactAttestation: no evidence hash");
        bytes32 role = who == Attester.PRADHAN
            ? pradhanRole(registry.villageOf(alertId))
            : (who == Attester.OFFICER ? OFFICER_ROLE : ORACLE_ROLE);
        require(hasRole(role, msg.sender), "ImpactAttestation: not this attester");
        require(attestations[alertId][who].by == address(0), "ImpactAttestation: already attested");
        attestations[alertId][who] = Attestation(msg.sender, severity, evidenceHash, uint64(block.timestamp));
        attesterCount[alertId] += 1;
        emit Attested(alertId, who, msg.sender, severity, evidenceHash);
        if (!confirmedEmitted[alertId] && isConfirmed(alertId)) {
            confirmedEmitted[alertId] = true;
            emit Confirmed(alertId);
        }
    }

    /// Two different keys attested severity >= 2.
    function isConfirmed(bytes32 alertId) public view returns (bool) {
        address first;
        for (uint8 i = 0; i < 3; i++) {
            Attestation storage a = attestations[alertId][Attester(i)];
            if (a.by == address(0) || a.severity < CONFIRMING_SEVERITY) continue;
            if (first == address(0)) first = a.by;
            else if (a.by != first) return true;
        }
        return false;
    }
}
