// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title FaceMatchRegistry
 * @dev On-chain registry for verified face match content fingerprints.
 * Records are keyed by an incrementing recordId to distinguish
 * "TAMPER DETECTED" (record exists, hash mismatch) from "RECORD NOT FOUND" (recordId never submitted).
 */
contract FaceMatchRegistry {
    struct Record {
        bytes32 contentHash;
        address submitter;
        uint256 timestamp;
        string metadataURI;   // Short off-chain reference, e.g. source URL or IPFS CID
        bool exists;
    }

    uint256 public nextRecordId;
    mapping(uint256 => Record) private records;

    event RecordSubmitted(
        uint256 indexed recordId,
        bytes32 contentHash,
        address indexed submitter,
        uint256 timestamp,
        string metadataURI
    );

    /**
     * @notice Submits a new content hash fingerprint to the registry.
     * @param contentHash SHA-256 / keccak256 fingerprint of the immutable verifiable data.
     * @param metadataURI Off-chain locator (e.g. source URL or content identifier).
     * @return recordId Unique, sequentially assigned record identifier.
     */
    function submitRecord(bytes32 contentHash, string calldata metadataURI)
        external
        returns (uint256 recordId)
    {
        recordId = nextRecordId;
        nextRecordId += 1;
        records[recordId] = Record(contentHash, msg.sender, block.timestamp, metadataURI, true);
        emit RecordSubmitted(recordId, contentHash, msg.sender, block.timestamp, metadataURI);
    }

    /**
     * @notice Retrieves a record by its stable identifier.
     * @param recordId The unique record ID to inspect.
     * @return contentHash The recorded fingerprint.
     * @return submitter Address that submitted the record.
     * @return timestamp Block timestamp when the record was written.
     * @return metadataURI Off-chain reference URI.
     * @return exists Boolean flag indicating whether this recordId was ever created.
     */
    function getRecord(uint256 recordId)
        external
        view
        returns (
            bytes32 contentHash,
            address submitter,
            uint256 timestamp,
            string memory metadataURI,
            bool exists
        )
    {
        Record memory r = records[recordId];
        return (r.contentHash, r.submitter, r.timestamp, r.metadataURI, r.exists);
    }
}
