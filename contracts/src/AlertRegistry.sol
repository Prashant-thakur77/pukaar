// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AlertRegistry: the notarised warning record
/// @notice One write when an alert first reaches a phone (anchorAlert) and one when it closes (anchorOutcome),
///         both by the Pukaar workflow's signer (ORACLE_ROLE). Each is write-once, so nobody can later claim no
///         warning was issued, back-date one or rewrite who heard it. capHash is keccak256 of the CAP 1.2 XML
///         served at capUri: anyone can fetch it and re-hash. No personal data: ids, levels, counts and hashes.
///         Replays and drills carry exercise = true, as CAP status=Exercise does.
contract AlertRegistry is AccessControl {
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");

    struct AlertRecord {
        bytes32 villageId; // keccak256 of the village id, e.g. keccak256("gohar")
        uint8 level; // 1 watch, 2 warning, 3 critical
        bytes32 capHash; // keccak256 of the CAP 1.2 XML as served at capUri
        string capUri; // the public URL, so anyone can re-hash it
        uint64 issuedAt; // the alert's creation time (unix seconds)
        bool exercise; // replay or drill (CAP status=Exercise)
        uint32 delivered; // filled by anchorOutcome
        uint32 acknowledged; // filled by anchorOutcome
        bytes32 afterActionHash; // filled by anchorOutcome: keccak256 of the after-action report
    }

    mapping(bytes32 alertId => AlertRecord) private _records;
    mapping(bytes32 alertId => bool) public outcomeAnchored;

    event AlertAnchored(bytes32 indexed alertId, bytes32 indexed villageId, uint8 level, bool exercise, bytes32 capHash);
    event OutcomeAnchored(bytes32 indexed alertId, uint32 delivered, uint32 acknowledged, bytes32 afterActionHash);

    constructor(address oracle) {
        require(oracle != address(0), "AlertRegistry: oracle is the zero address");
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(ORACLE_ROLE, oracle);
    }

    function anchorAlert(bytes32 alertId, AlertRecord calldata r) external onlyRole(ORACLE_ROLE) {
        require(alertId != bytes32(0), "AlertRegistry: empty alert id");
        require(_records[alertId].issuedAt == 0, "AlertRegistry: alert already anchored");
        require(r.level >= 1 && r.level <= 3, "AlertRegistry: level must be 1 (watch), 2 (warning) or 3 (critical)");
        require(r.villageId != bytes32(0), "AlertRegistry: no village");
        require(r.capHash != bytes32(0), "AlertRegistry: no CAP hash");
        require(r.issuedAt != 0, "AlertRegistry: no issue time");
        require(
            r.delivered == 0 && r.acknowledged == 0 && r.afterActionHash == bytes32(0),
            "AlertRegistry: the outcome is anchored at close, not with the alert"
        );
        _records[alertId] = r;
        emit AlertAnchored(alertId, r.villageId, r.level, r.exercise, r.capHash);
    }

    function anchorOutcome(bytes32 alertId, uint32 delivered, uint32 acknowledged, bytes32 afterActionHash)
        external
        onlyRole(ORACLE_ROLE)
    {
        AlertRecord storage r = _records[alertId];
        require(r.issuedAt != 0, "AlertRegistry: alert not anchored");
        require(!outcomeAnchored[alertId], "AlertRegistry: outcome already anchored");
        outcomeAnchored[alertId] = true;
        r.delivered = delivered;
        r.acknowledged = acknowledged;
        r.afterActionHash = afterActionHash;
        emit OutcomeAnchored(alertId, delivered, acknowledged, afterActionHash);
    }

    function get(bytes32 alertId) external view returns (AlertRecord memory) {
        return _records[alertId];
    }

    function exists(bytes32 alertId) external view returns (bool) {
        return _records[alertId].issuedAt != 0;
    }

    function levelOf(bytes32 alertId) external view returns (uint8) {
        return _records[alertId].level;
    }

    function villageOf(bytes32 alertId) external view returns (bytes32) {
        return _records[alertId].villageId;
    }

    function isExercise(bytes32 alertId) external view returns (bool) {
        return _records[alertId].exercise;
    }
}
