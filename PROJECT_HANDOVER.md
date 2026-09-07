# Project Handover Document

## Project: Face ID + Blockchain Verification (HH Goa 2026 Task #3)
**Status:** Complete & Fully Verified
**Test Suite Status:** 36/36 Pytest Tests Passing (100%)
**Live Demonstration Status:** Validated (`scripts/run_demo_pipeline.py` & `scripts/test_tamper.py` passing with genuine on-chain reads, tamper detection, and field-level diffs)

---

## 1. System Architecture Overview

The system provides an autonomous, verifiable end-to-end pipeline connecting computer vision, dynamic multi-engine reverse image search, biometric validation, cryptographic canonicalization, and real EVM smart contracts.

```
Input Image → Face Detection (MTCNN/OpenCV) → Quality Validation (Blur/Size)
→ 512-d Face Embedding (InceptionResnetV1)
→ Search Representations [Full Image Context (A), Padded Face Crop (B)]
→ Dynamic Multi-Provider Search Cascade (Google AI Studio Gemini Search Grounding → SerpApi Google Lens → TinEye)
→ Deduplication & Live Page Fetching (httpx + BeautifulSoup)
→ Face Verification (Candidate Face Embedding vs. Original Embedding)
→ Automatic Best Match Selection (Calibrated Threshold + Margin Filtering)
→ Two-Tier Data Split (Immutable Verifiable vs. Audit Metadata)
→ SHA-256 Canonical Hashing
→ Blockchain Record Write via `submitRecord(contentHash, metadataURI)`
→ Stable `recordId` + Transaction Hash returned
→ Independent Re-Verification `(recordId, data)` with 6 distinct status outcomes.
```

---

## 2. Directory Structure & Key Subsystems

- `contracts/`:
  - `FaceMatchRegistry.sol`: Solidity 0.8.20 smart contract keyed by sequential `recordId` (`submitRecord`, `getRecord`, `totalRecords`, `RecordSubmitted` event).
- `pipeline/`:
  - `face/`:
    - `detector.py`: MTCNN/OpenCV fallback face detector with blur variance check (Laplacian) and minimum size checks.
    - `embedder.py`: InceptionResnetV1 512-d L2-normalized embeddings & cosine similarity calculations.
  - `search/`:
    - `base.py`: Abstract `SearchProvider` and normalized `SearchResult` data model.
    - `representations.py`: Search representations (Full Image A and Padded Face Crop B).
    - `gemini_search.py`: Google AI Studio Gemini API Search Grounding provider.
    - `serpapi_search.py`: SerpApi Google Lens reverse search provider.
    - `tineye_search.py`: TinEye API reverse search provider.
    - `cascade.py`: Multi-provider cascade orchestrator with duplicate URL suppression.
    - `fetch_candidates.py`: Live HTML page scraper (httpx + BeautifulSoup) and image downloader.
  - `match/`:
    - `matcher.py`: Candidate face verification against original face embedding with calibrated threshold & margin ambiguity checks.
    - `extractor.py`: Structured post metadata extraction & perceptual hashing (dHash/pHash).
  - `canon/`:
    - `canonicalize.py`: Two-tier data model split (`ImmutableVerifiableData` vs. `AuditMetadata`) and deterministic SHA-256 canonical hashing.
  - `chain/`:
    - `abi.py`: Pre-compiled universal EVM bytecode (EVM target `paris`) & ABI.
    - `client.py`: Robust Web3 client for Polygon Amoy Testnet (with dedicated Alchemy/Infura RPC support and fallback endpoints), Local EVM / In-Memory chains, startup diagnostics, and granular exception hierarchy.
    - `writer.py`: `submitRecord` transaction creation, gas buffering, receipt waiting, and `recordId` extraction.
    - `reader.py`: `getRecord` on-chain reader querying `(contentHash, metadataURI, timestamp, submitter)`.
  - `storage/`:
    - `cache.py`: SQLite local cache & audit log (explicitly used as cache/audit log, never as verification substitute).
  - `verifier.py`: 6-state independent verification engine (`VERIFIED`, `TAMPER DETECTED`, `RECORD NOT FOUND`, `HASH MISMATCH`, `REVOKED`, `NETWORK ERROR`).
  - `pipeline.py`: Orchestrated end-to-end pipeline runner.
- `scripts/`:
  - `deploy_contract.py`: Contract deployer for Polygon Amoy or Local Chain with startup diagnostics.
  - `calibrate_threshold.py`: Threshold calibration utility generating `calibration_report.md`.
  - `test_tamper.py`: Live demonstration script of `VERIFIED`, `TAMPER DETECTED`, and `RECORD_NOT_FOUND`.
- `server/`:
  - `app.py`: FastAPI server with `/api/scan`, `/api/verify`, `/api/records`, `/api/status`, `/api/blockchain/diagnostics`.
  - `static/index.html`, `static/style.css`, `static/app.js`: Cyberpunk glassmorphism web interface with webcam capture, pipeline stepper, candidate match cards, two-tier JSON inspector, and verification sandbox.
- `tests/`:
  - `test_face.py` (5 tests)
  - `test_search.py` (6 tests)
  - `test_matcher.py` (3 tests)
  - `test_canonicalize.py` (4 tests)
  - `test_blockchain.py` (10 tests)
  - `test_verify.py` (6 tests)
- `main.py`: Command-line interface for pipeline execution.
- `verify.py`: Independent CLI verification tool with field-level diff display.
- `calibration_report.md`: Documented threshold sweeps and decision justification.
- `PRD.md`: Master specification.
- `README.md`: Setup, architecture, pricing, faucets, and usage guide.
- `TODO.md`: Execution checklist (100% completed).

---

## 3. How to Run & Verify

### Run the Test Suite
```bash
python -m pytest tests/ -v
```

### Run the Live Tamper Detection Demonstration
```bash
python scripts/test_tamper.py
```

### Run Pipeline via CLI
```bash
python main.py --image path/to/input.jpg
```

### Verify a Record via CLI
```bash
python verify.py --record-id 1 --data path/to/exported_data.json
```

### Run the Web Dashboard
```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000
```
Then open `http://127.0.0.1:8000` in any web browser.

---

## 4. Key Architectural Decisions & Safeguards

1. **Multi-Provider Search Cascade & Resilient Fallback:**
   - Primary: Google AI Studio Gemini API with Google Search Grounding (`GEMINI_API_KEY`).
   - Fallback: SerpApi Google Lens engine (utilizing official two-step image upload via `https://serpapi.com/image` and Google Lens candidate query).
   - Candidate discovery merge across Representation A (Full Scene Context) and Representation B (Padded Face Crop).
2. **Two-Tier Data Split & Hash Invariance:**
   - Dynamic audit metadata (`recheck_count`, `search_timestamp`, `api_response_time_ms`, etc.) is explicitly separated into `AuditMetadata` and excluded from `ImmutableVerifiableData`.
   - Verified via automated regression tests (`test_audit_metadata_drift_does_not_break_hash`).
3. **Deterministic Canonicalization:**
   - Float precision normalization (fixed to 6 decimal places).
   - ISO-8601 UTC timestamp format without microsecond drift (`YYYY-MM-DDTHH:MM:SSZ`).
   - UTF-8 byte encoding with recursive alphabetical key sorting.
4. **Sequential On-Chain Keying (`recordId`):**
   - The smart contract records data indexed by sequential integer `recordId`, returned in the `RecordSubmitted` event.
   - Verification accepts `(recordId, candidate_data)`, canonicalizes and hashes `candidate_data`, retrieves `getRecord(recordId)` from the blockchain, and performs cryptographic comparison.
5. **Universal EVM Compatibility:**
   - Compiled with `evm_version="paris"` in Solidity 0.8.20 to avoid `PUSH0` opcode incompatibility across local test chains and live testnets.
