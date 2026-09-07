# PRD & Technical Specification (v2 — Corrected)
## HH Goa 2026 — Task #3: Face ID + Blockchain Verification

**Version:** 2.0 · **Status:** Implementation-ready, corrected · **Baseline:** v1.0, revised per architectural review

This is a revision of the v1 PRD, not a rewrite. Everything in v1 that is not called out below is unchanged: the ethical framing (consented-input-only), the general technology categories, the phased roadmap shape, and the overall folder layout survive intact. Nine issues were identified in v1 and are corrected here.

---

## 1. Executive Summary

The pipeline is: **face scan → genuine multi-provider web search → matched post → canonical fingerprint → blockchain record → independent re-verification via a stable record identifier.**

Key architectural principles:
- Search uses multi-provider cascade (Google Cloud Vision → SerpApi → TinEye) and multi-representation queries (Full Image Context + Padded Face Crop).
- Re-verification works off a **stable on-chain record identifier** (`recordId`), not raw hash lookup, correctly distinguishing `TAMPER DETECTED` from `RECORD_NOT_FOUND`.
- The canonical fingerprint contains only stable content properties (Immutable Verifiable Data). Timestamps and run-specific telemetry are stored separately as Audit Metadata.
- Local storage (SQLite) is explicitly a **cache / audit log**, never a substitute for an on-chain read.
- Multiple-face handling defaults to auto-selecting the largest face by bounding-box area while logging all detections.
- Automatic matching with calibrated similarity threshold and margin filtering; human review mode is optional and off by default.
- Polygon Amoy testnet is the primary public blockchain with native gas token POL.

---

## 2. Pipeline Architecture & Data Flow

```
INPUT IMAGE
   ↓ validate (format/size)
FACE DETECTION (MTCNN / FaceNet / OpenCV)
   ↓ multiple faces? → auto-select largest, log all detections
FACE QUALITY VALIDATION (blur variance, min dimensions)
   ↓
FACE EMBEDDING (InceptionResnetV1 / ArcFace 512-d L2-normalized)
   ↓
SEARCH REPRESENTATIONS:
   ├── Representation A: Full Original Image (scene/context)
   └── Representation B: Padded Face Crop (20% margin)
   ↓
PRIMARY SEARCH: Google Cloud Vision Web Detection (both representations)
   ↓ (on provider error or 0 candidates)
FALLBACK SEARCH: SerpApi Google Lens (both representations)
   ↓ (optional, if still 0 candidates)
TERTIARY FALLBACK: TinEye API (Representation A)
   ↓
DYNAMIC CANDIDATE DISCOVERY: Merge & deduplicate across active providers
   ↓
CANDIDATE COLLECTION: Live HTTP page fetch & image extraction
   ↓
FACE VALIDATION: Compare original embedding vs candidate face embeddings (cosine similarity)
   ↓
AUTOMATIC BEST-MATCH SELECTION: Calibrated threshold + margin check
   ↓
DATA EXTRACTION: Extract platform, URL, post ID, text, image hash
   ↓
CANONICAL DATA SPLIT:
   ├── Immutable Verifiable Data → Canonical JSON → SHA-256 → contentHash (bytes32)
   └── Audit/Run Metadata → Saved to local cache only
   ↓
BLOCKCHAIN WRITE: submitRecord(contentHash, metadataURI) on Polygon Amoy / EVM
   ↓ Returns (recordId, tx_hash)
STABLE IDENTIFIER RECORDED in local metadata cache
   ↓
INDEPENDENT RE-VERIFICATION (recordId, data_to_verify):
   1. Canonicalize data_to_verify → if invalid: INSUFFICIENT_DATA
   2. Compute new_hash = SHA256(canonical_bytes)
   3. Read getRecord(recordId) on-chain → if not found: RECORD_NOT_FOUND
   4. Compare new_hash == on_chain_contentHash → if mismatch: TAMPER DETECTED
   5. Check source URL live → if unreachable: SOURCE_UNAVAILABLE; else: VERIFIED
   (If RPC is down: CHAIN_RPC_ERROR — never fall back to local cache)
```

---

## 3. Two-Tier Data Model Specification

### A. Immutable Verifiable Data (Hashed into contentHash)
```json
{
  "image_sha256": "<sha256_of_candidate_image_bytes>",
  "normalized_source_url": "https://example.com/post/123",
  "platform": "twitter",
  "public_post_id": "123",
  "post_text_normalized": "post title or caption content",
  "schema_version": "1.0"
}
```

### B. Audit / Run Metadata (Stored in SQLite cache, NOT hashed)
```json
{
  "api_response_time_ms": 420,
  "discovery_timestamp": "2026-09-06T00:15:00Z",
  "embedding_model_version": "facenet-inceptionresnetv1-vggface2-512d",
  "image_phash": "d4f8a2...",
  "pipeline_execution_timestamp": "2026-09-06T00:15:02Z",
  "search_provider": "google_vision",
  "search_representation_used": "full_image",
  "similarity_score": 0.885
}
```

---

## 4. Smart Contract Specification

Contract: `contracts/FaceMatchRegistry.sol`
```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract FaceMatchRegistry {
    struct Record {
        bytes32 contentHash;
        address submitter;
        uint256 timestamp;
        string metadataURI;
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

    function submitRecord(bytes32 contentHash, string calldata metadataURI)
        external
        returns (uint256 recordId);

    function getRecord(uint256 recordId)
        external
        view
        returns (
            bytes32 contentHash,
            address submitter,
            uint256 timestamp,
            string memory metadataURI,
            bool exists
        );
}
```

---

## 5. Verification Status Outputs (6 Distinct States)

1. `VERIFIED`: Canonical hash matches on-chain `contentHash` for given `recordId` and live URL is reachable.
2. `TAMPER DETECTED`: `recordId` exists on-chain, but the computed hash of the supplied data does not match the on-chain `contentHash`.
3. `RECORD_NOT_FOUND`: `getRecord(recordId)` returns `exists == false`. The `recordId` was never registered on-chain.
4. `INSUFFICIENT_DATA`: The provided verification payload is missing mandatory immutable fields or cannot be canonicalized.
5. `SOURCE_UNAVAILABLE`: Hash integrity is confirmed on-chain, but the live source URL cannot be reached.
6. `CHAIN_RPC_ERROR`: The blockchain RPC endpoint is unreachable or returned a network/protocol error. Local cache is explicitly not substituted.
