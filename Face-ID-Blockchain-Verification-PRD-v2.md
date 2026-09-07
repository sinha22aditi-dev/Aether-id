# PRD & Technical Specification (v2 — Corrected)
## HH Goa 2026 — Task #3: Face ID + Blockchain Verification

**Version:** 2.0 · **Status:** Implementation-ready, corrected · **Baseline:** v1.0, revised per architectural review

This is a revision of the v1 PRD, not a rewrite. Everything in v1 that is not called out below is unchanged: the ethical framing (consented-input-only), the general technology categories, the phased roadmap shape, and the overall folder layout survive intact. Nine issues were identified in v1 and are corrected here. Section numbers below map to the original document; changed sections are marked **[REVISED]**.

---

## 1. Executive Summary **[REVISED]**

The pipeline remains: **face scan → genuine multi-provider web search → matched post → canonical fingerprint → blockchain record → independent re-verification via a stable record identifier.**

Key changes from v1:
- Search no longer depends on a single provider or a single image representation (Correction 1).
- Re-verification now works off a **stable on-chain record identifier**, not a raw hash lookup, so it can correctly distinguish "tampered" from "never recorded" (Correction 2).
- The canonical fingerprint now only includes fields that are genuinely stable; timestamps and other run-specific data are tracked separately as audit metadata (Correction 3).
- Local storage (SQLite) is explicitly relabeled as a **cache**, never a substitute for an on-chain read (Correction 4).
- Multiple-face handling, human confirmation, API auth, and similarity thresholds are each standardized to one clear default behavior (Corrections 5–8).
- All quantitative claims about external services are marked with their source and confidence, and anything that can change is flagged for re-verification at implementation time (Correction 9).

The consented-input-only rule from v1 stands unchanged: this pipeline is only to be run against faces the operator has explicit consent to search.

---

## 2. Requirement Traceability Table **[updated rows only shown; all other rows from v1 unchanged]**

| # | Requirement | Mandatory/Optional | Proposed Implementation (v2) | Evidence in Demo | Failure Risk |
|---|---|---|---|---|---|
| R3 | Genuine runtime search, not hardcoded | Mandatory | Multi-representation, multi-provider search (Sec. 13) — no single point of failure | Logs show which provider/representation found the winning candidate, varies run to run | Medium (was High) |
| R6 | Blockchain record, tamper-evident, retrievable | Mandatory | Record keyed by an incrementing on-chain `recordId`, not by content hash (Sec. 16–17) | `recordId` + tx hash shown, PolygonScan/OKLink link opened live | Medium |
| R8 | Independent re-verification, 6 clear outputs | Mandatory | Verification takes `(recordId, data)`, retrieves original record by ID, then compares hashes (Sec. 17) | Live VERIFIED vs TAMPER DETECTED vs RECORD_NOT_FOUND demo | Medium |
| R-new | No single point of failure in search | Added (Correction 1) | ≥2 independent search providers, ≥2 image representations | Logs show fallback trigger on demand | Medium |
| R-new | Verification must distinguish tamper vs. unknown | Added (Correction 2) | Stable record identifier scheme | Test case: unrelated random data on a *valid* recordId → TAMPER DETECTED; unrelated data on a *fake* recordId → RECORD_NOT_FOUND | Low once implemented |
| R-new | Canonical fingerprint must be stable across rediscovery | Added (Correction 3) | Two-tier data model (Sec. 15) | Re-running discovery on the same live post yields the same hash despite a new timestamp | Low |

---

## 3–5. Requirement Analysis, Assumptions, Major Risks **[REVISED — updated risk list]**

Previously flagged risks are unchanged except:
- **Reverse-image search ≠ face search** is now mitigated more robustly by using two search providers and two image representations instead of relying on face-crop-only queries to one provider (Sec. 13).
- **New risk (identified during this revision): keying blockchain records by content hash created an unresolvable ambiguity between "tampered" and "never recorded."** This is fixed by switching to identifier-based lookup (Sec. 16–17). This was the single most important logical bug in v1 and is now fully corrected.
- **New risk: quoted pricing/quota numbers for external services drift over time and some are contested across sources.** Mitigated by explicitly marking anything not independently confirmed as "verify before implementation" (Sec. 9, new callout table).

---

## 13. Genuine Search Architecture **[REVISED — Correction 1]**

**Problem in v1:** the search step sent only a cropped face image to a single provider (Google Vision Web Detection). Reverse-image/web-detection systems are general-purpose visual similarity engines, not dedicated face-recognition search engines — an isolated face crop, stripped of background/clothing/context, is often a *worse* query for these systems than the fuller original photo, and a single provider is a single point of failure regardless.

**Corrected design:**

```
INPUT IMAGE
   ↓
SEARCH REPRESENTATIONS
   ├── Representation A: full original image (resized, JPEG) — richer visual context (background,
   │   clothing, setting) that general-purpose reverse-image engines actually key on
   └── Representation B: padded face crop (20% margin around bbox) — isolates the face itself,
       useful when the background is generic/unhelpful or when a provider is face-search-tuned
   ↓
PRIMARY SEARCH — Google Cloud Vision Web Detection, called once per representation (A then B)
   ↓
   if primary provider errors (auth/quota/network) OR returns zero total candidates
   across both representations:
   ↓
FALLBACK SEARCH — SerpApi Google Lens endpoint, called on the same two representations
   ↓
   if fallback also returns zero candidates (optional, cost-permitting):
   ↓
TERTIARY FALLBACK (optional) — TinEye API, near-duplicate focused, representation A only
   ↓
DYNAMIC CANDIDATE DISCOVERY — merge all candidates returned by whichever provider(s) actually ran,
   deduplicate by normalized URL
   ↓
CANDIDATE COLLECTION — fetch each candidate page live (httpx), extract image + text
   ↓
FACE VALIDATION — every candidate image is checked against the ORIGINAL face embedding
   (never against representation A or B directly — those were only search queries, not the
   ground truth for matching)
   ↓
BEST MATCH SELECTION — automatic, threshold + margin (Sec. 14, Correction 6: no human step required)
```

**Which representation is used when, and why:** representation A (full image) is tried first because general web/reverse-image indexes are built on whole-scene visual similarity, and a face crop alone often returns weak or irrelevant results from these systems. Representation B (face crop) is still run in the same pass (not only as a fallback) because some genuinely matching pages may only be found when the query is tightly cropped to the face — e.g., if the original photo's background is a generic domestic setting that visually dominates the whole-image search. Running both representations against the primary provider by default is a query-count cost roughly double a single-representation design, which is a deliberate trade-off for hackathon-grade reliability rather than a production-cost-optimized design; this is called out honestly in the README as a known cost trade-off, with a config flag (`SEARCH_USE_FULL_IMAGE=true/false`, `SEARCH_USE_FACE_CROP=true/false`) to disable either representation if quota becomes a concern.

**No single point of failure, concretely:** the `SearchProvider` interface (unchanged from v1's abstract design) now has three concrete implementations, tried in a defined cascade rather than the system depending on any one of them succeeding. If Google Vision is down or its quota is exhausted, the pipeline automatically proceeds to SerpApi without any code change or manual intervention — this is what "no single point of failure" means in this design, not that all three always run.

**Proving genuineness on camera:** log lines show, for each provider actually invoked: request timestamp, which representation was sent, raw candidate count returned. Running the pipeline twice on two different consented photos in the same recording should visibly show different providers/representations winning and different candidate URLs — direct evidence against hardcoding.

**What happens if all providers fail or return nothing:** `SEARCH_PROVIDER_UNAVAILABLE` (all providers errored) or `NO_MATCH` (providers succeeded, zero candidates) — both are clean, loggable terminal states, not crashes (unchanged from v1, Sec. 18).

---

## 14. Candidate Discovery and Match Validation **[REVISED — Correction 6, 8]**

**Correction 6 — automatic matching only:** the production/demo flow performs candidate scoring, ranking, threshold filtering, and best-match selection **entirely automatically**. There is no interactive confirmation step in this flow. An **optional, clearly separate** `--review` flag launches a human-review mode that pauses before committing to chain and shows the operator the top-N candidates with scores for manual inspection — this exists only for debugging/tuning during development, is off by default, and must not be used in the graded demo recording (the demo must show the system deciding on its own).

**Correction 8 — threshold calibration, not a fixed magic number:** v1 presented `0.42` as if it were a validated constant. It is not. The corrected process:

1. Assemble a small labeled calibration set from **consented** photos only: at least 10 genuine pairs (same person, two different photos) and at least 10 impostor pairs (different people), run through the exact chosen embedding model (InsightFace `buffalo_l` or its dlib fallback — thresholds are **not** portable between the two models).
2. Compute cosine similarity for every pair; a calibration script (`scripts/calibrate_threshold.py`) plots/reports the genuine-pair and impostor-pair score distributions.
3. Select the threshold that minimizes combined false-accept + false-reject error on this set, or — if a bias is desired — pick the threshold that keeps the false-accept rate near zero even at the cost of some false rejections (recommended for this project, since a false *accept* here means writing an incorrect identity match to an immutable ledger, which is the worse failure mode).
4. Add a required minimum score margin between the top-1 and top-2 candidate (default 0.05) to reject ambiguous near-ties automatically rather than silently picking one.
5. **Document the exact calibration set size, the chosen threshold, and the model version used in the README**, explicitly as a small-sample heuristic, not a certified biometric threshold — this honesty requirement carries over from v1's "known limitations" spirit and is now made a concrete deliverable (a `calibration_report.md` or similar, produced by the script).

The rest of Section 14 (candidate image sourcing, multi-face-per-candidate handling, evidence retention) is unchanged from v1.

---

## 15. Data Fingerprinting and Canonicalization **[REVISED — Correction 3]**

**Problem in v1:** `discovery_timestamp` and other run-specific values were included directly in the hashed canonical record. Rediscovering the exact same still-live post a week later would legitimately produce a new timestamp, which would change the hash and make the *same, unmodified* real-world content look like a different (or "tampered") record. That's a false signal, not a security feature.

**Corrected two-tier data model:**

### A. Immutable Verifiable Data (hashed, part of the fingerprint)
```
normalized_source_url
platform
public_post_id            (nullable)
post_text_normalized      (nullable)
image_sha256               (hash of the downloaded candidate image bytes)
schema_version
```
These are the only fields that determine VERIFIED vs. TAMPER DETECTED. All are things that should be stable properties of *the content itself*, not of *the act of discovering it*.

### B. Audit / Run Metadata (stored off-chain, NOT hashed)
```
discovery_timestamp
pipeline_execution_timestamp
similarity_score
search_provider              (google_vision | serpapi | tineye)
search_representation_used   (full_image | face_crop)
embedding_model_version      (e.g. "insightface-buffalo_l-v0.7")
api_response_time_ms
image_phash                  (perceptual hash — informational only, never authoritative)
```
This block is fully retained (in the local cache, Sec. 16A/Correction 4) for traceability, debugging, and demo narration, but changing it never affects the hash or the VERIFIED/TAMPER DETECTED outcome. This is the mechanism that makes re-verification stable across time and across re-runs of discovery.

**Canonicalization function (unchanged mechanism, updated scope):** `json.dumps(immutable_fields, sort_keys=True, separators=(",", ":"))` → SHA-256. `test_canonicalize_idempotent()` is extended with a new test: build the same immutable-field dict with two *different* audit-metadata blocks attached (simulating two separate discovery runs of the same live post) and assert the resulting hash is identical — this is the regression test that directly proves Correction 3 is implemented correctly.

Missing-field handling, text normalization, URL normalization, and hash algorithm choice (SHA-256) are unchanged from v1.

---

## 16. Blockchain Architecture **[REVISED — Corrections 2, 4, 9]**

### 16A. Local storage is a cache, not a verification source **[Correction 4]**

SQLite is retained in the architecture but its role is corrected and relabeled everywhere in this document as: **local metadata cache / audit log**, never "blockchain fallback" and never treated as equivalent evidence to an on-chain read. Concretely:

- SQLite stores: the full canonical record (both immutable and audit fields), the returned `recordId`, and the tx hash — purely so `verify.py` doesn't require the operator to retype the entire record by hand.
- **If the blockchain RPC is unreachable at verification time, `verify.py` must not silently fall back to trusting the SQLite copy as if it were a verified result.** It must report a distinct, honest status — `CHAIN_RPC_ERROR` (a new internal error state, surfaced to the user as "cannot currently verify — chain unreachable," not conflated with any of the six defined verification outcomes) — and may *optionally* show the cached local copy purely for reference, clearly labeled "unverified local cache, not a blockchain confirmation."
- The only legitimate blockchain **fallback** (as opposed to non-blockchain cache) is the local Hardhat node described below, because it is still a real, code-executing EVM chain that performs a genuine write/read cycle — it is just not publicly, independently checkable by someone outside the team, which is why it remains demoted to fallback status.

### 16B. Blockchain comparison and choice (unchanged from v1, restated)

| Approach | Independently verifiable by an outside reviewer? | Reliability | Cost | Recommended role |
|---|---|---|---|---|
| **Polygon Amoy public testnet** | **Yes** — anyone can look up the tx/record on a public explorer | High | Free (testnet gas) | **Primary** |
| Local Hardhat node | No — only verifiable by someone running your node | Very high (no external dependency) | Free | Fallback (demo-safety net only) |
| Simulated/local hash-chain (no real EVM) | No | Highest | Free | Not recommended even as fallback — doesn't exercise a real chain at all |
| Mainnet | Yes, strongest | High | Real money | Unnecessary cost/risk for a hackathon |

### 16C. Corrected on-chain data model **[Correction 2 — the core fix]**

**Root cause of the v1 bug:** the v1 contract keyed records **by content hash**. Verification recomputed a hash from the data-to-check and looked *that* hash up directly. Under that scheme, "data that was tampered" and "data that was never submitted at all" produce exactly the same signal — neither hash is found on-chain — so the system could never distinguish them. Returning "TAMPER DETECTED" for both would be dishonest (some of that data was simply never recorded, which is a different situation), and returning "RECORD NOT FOUND" for both would fail to actually catch tampering of real records.

**Fix:** key records by a **stable, sequential on-chain identifier** (`recordId`), independent of content. Verification is always given `(recordId, data_to_verify)` — the identifier is the caller's *claim* "this data is supposed to match what's stored under this ID," and the system checks that claim, rather than doing a blind hash search.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract FaceMatchRegistry {
    struct Record {
        bytes32 contentHash;
        address submitter;
        uint256 timestamp;
        string metadataURI;   // short off-chain reference, e.g. source URL or IPFS CID
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
        returns (uint256 recordId)
    {
        recordId = nextRecordId;
        nextRecordId += 1;
        records[recordId] = Record(contentHash, msg.sender, block.timestamp, metadataURI, true);
        emit RecordSubmitted(recordId, contentHash, msg.sender, block.timestamp, metadataURI);
    }

    function getRecord(uint256 recordId)
        external
        view
        returns (bytes32 contentHash, address submitter, uint256 timestamp, string memory metadataURI, bool exists)
    {
        Record memory r = records[recordId];
        return (r.contentHash, r.submitter, r.timestamp, r.metadataURI, r.exists);
    }
}
```

- **Stable identifier returned at write time:** `recordId` (small integer, easy to reference/print/say out loud in the demo) plus the transaction hash (for explorer lookup). Both are returned to the caller and stored in the local cache.
- **Duplicate handling:** no longer prevented at the contract level (since identity is now assigned sequentially, not derived from content) — instead, before writing, the pipeline checks the local cache for an existing record whose immutable fields canonicalize to the same hash, and if found, logs `DUPLICATE_CONTENT_DETECTED` and asks whether to reuse the existing `recordId` or write a new one anyway (both are legitimate; re-submission is not an error at the contract level).
- **Wallet, gas token, RPC:** unchanged mechanism from v1, with a factual correction (Correction 9, Sec. 9): Polygon's native gas token was renamed **POL** (previously MATIC); the **official Polygon-run faucet has been discontinued**, so funding must go through a third-party faucet (Alchemy's Amoy faucet, QuickNode's, or Chainlink's) — this must be documented explicitly in the README's setup steps since it changed after most existing tutorials were written.

---

## 17. Independent Re-Verification Architecture **[REVISED — Correction 2]**

```
Write time:
ORIGINAL DATA → CANONICALIZATION (immutable fields only) → ORIGINAL HASH
   → CHAIN WRITE (submitRecord) → STABLE IDENTIFIER RETURNED (recordId + tx hash)

Verification time, input = (recordId, data_to_verify):
   ↓
1. Attempt to canonicalize data_to_verify using the immutable-field schema.
   → if required immutable fields are missing/unparseable: return INSUFFICIENT_DATA (stop here)
   ↓
2. Compute new_hash = SHA-256(canonical bytes)
   ↓
3. Call getRecord(recordId) — read-only, no wallet/gas needed
   → if exists == false: return RECORD_NOT_FOUND (this recordId was never written — correctly
     distinguished from "this data was tampered," because there is no original to compare against)
   ↓
4. Compare new_hash to the on-chain contentHash for that recordId
   → if new_hash != contentHash: return TAMPER DETECTED (a real record exists at this ID,
     but the data now supplied does not match what was originally committed — this is the
     scenario v1 could not correctly identify)
   → if new_hash == contentHash: continue to step 5
   ↓
5. (Optional, non-authoritative) Live HTTP check of normalized_source_url.
   → if unreachable: return SOURCE_UNAVAILABLE (hash-level integrity is confirmed; the live
     source is simply not currently reachable — reported as a distinct, less alarming status
     than TAMPER DETECTED, since it says nothing about the data's integrity)
   → if reachable: return VERIFIED
```

This directly resolves Correction 2: **unrelated data checked against a `recordId` that was never written returns `RECORD_NOT_FOUND`; genuinely modified data checked against a `recordId` that *was* written returns `TAMPER DETECTED`.** These are now structurally different code paths (step 3 vs. step 4), not the same "hash not found" outcome.

**Tampering demonstration (updated for the recording):**
1. `verify.py --record-id 7 --canonical-json original.json` → `VERIFIED`.
2. Edit one field in a copy → `verify.py --record-id 7 --canonical-json modified.json` → `TAMPER DETECTED`, with a field-level diff against the cached original shown for human readability (diagnostic only — the actual TAMPER DETECTED decision came from the hash comparison in step 4, not from the diff).
3. **New test case, added because of this correction:** `verify.py --record-id 999 --canonical-json anything.json` (a `recordId` that was never submitted) → `RECORD_NOT_FOUND`, proving the system does not conflate "never recorded" with "tampered."

---

## 9/10. External Services and Environment Variables **[REVISED — Correction 7, 9]**

### Correction 7 — one primary auth path per service, no ambiguity

| Service | Purpose | Auth Method (single, standardized) | Env Var(s) | Local Dev | Deployment |
|---|---|---|---|---|---|
| Google Cloud Vision API | Primary search (Web Detection) | Service-account JSON key (the officially recommended path for server-side apps) — **the alternate bare-API-key REST method is intentionally not supported**, to avoid two divergent auth code paths | `GOOGLE_APPLICATION_CREDENTIALS` (path to JSON file) | Local JSON file, gitignored | Secret file mount or secret-manager-injected file, referenced by the same env var |
| SerpApi | Fallback search | Bearer key, single documented method | `SERPAPI_KEY` | `.env` | Platform secret var |
| TinEye API (optional tertiary) | Last-resort fallback search | API key + secret, HMAC request signing per TinEye's documented method | `TINEYE_API_KEY`, `TINEYE_API_SECRET` | `.env` | Platform secret vars |
| Alchemy | Blockchain RPC | API key embedded in the RPC URL (Alchemy's only supported method for this use case) | `BLOCKCHAIN_RPC_URL` | `.env` | Platform secret var |
| Wallet (self-generated) | Signs on-chain writes | Raw ECDSA private key via `eth_account` (a keystore-file+password alternative exists in the ecosystem but is **not** used here, to keep exactly one method) | `WALLET_PRIVATE_KEY` | `.env`, never committed | Platform secrets manager |
| Deployed contract | Record storage | N/A — public read; writes require the wallet key above | `CONTRACT_ADDRESS` | `.env` after deploy script runs | `.env`/deploy config |

New/changed env vars vs. v1: `TINEYE_API_KEY`, `TINEYE_API_SECRET` (optional tertiary fallback), `SEARCH_USE_FULL_IMAGE`, `SEARCH_USE_FACE_CROP` (representation toggles), `FACE_SELECTION_MODE` (`largest` default, `interactive` optional — Correction 5), `MATCH_REVIEW_MODE` (`off` default, `interactive` optional — Correction 6). `SIMILARITY_THRESHOLD` remains but its docstring/comment in `.env.example` now explicitly says "initial value — recalibrate with `scripts/calibrate_threshold.py` before relying on it" (Correction 8).

### Correction 9 — facts that must be re-verified at implementation time

| Claim | Status as researched for this revision | Action required |
|---|---|---|
| Google Vision: first 1,000 units/month free per feature | Corroborated by Google's own pricing page and multiple independent sources | Low risk, but re-check `cloud.google.com/vision/pricing` before implementation since pricing pages change |
| Google Vision Web Detection: **$3.50 per 1,000 units** (units 1,001–5,000,000/month) — **this corrects v1, which incorrectly quoted the general $1.50 rate for this feature** | Corroborated by Google's official pricing page and independent secondary sources | Re-verify at implementation; Web Detection is billed at a different, higher rate than most other Vision features |
| SerpApi free trial (~100 searches/month) | Not independently re-confirmed in this revision | **[VERIFY AT IMPLEMENTATION]** — check serpapi.com directly |
| TinEye API free tier | Historically very limited/commercial-focused | **[VERIFY AT IMPLEMENTATION]** — may require a paid plan even for light testing; treat as optional, not load-bearing |
| Polygon Amoy testnet is active in 2026, chain ID 80002 | Corroborated by multiple current sources | Low risk |
| Polygon's native gas token is now called **POL**, not MATIC | Corroborated by multiple 2026 sources | Update all docs/UI copy to say POL |
| **The official Polygon-run faucet has been discontinued**; third-party faucets (Alchemy, QuickNode, Chainlink, GetBlock) must be used instead | Corroborated by Polygon's own developer docs | This is a material change from what most older tutorials say — document it explicitly in the README |
| Alchemy free-tier RPC request limits | Not independently re-confirmed with a specific number in this revision | **[VERIFY AT IMPLEMENTATION]** — check alchemy.com's current pricing page rather than assuming a fixed quota |

No claim in this PRD about cost, quota, or auth method should be treated as final without checking the provider's live documentation immediately before building — this table exists precisely to flag which specific claims need that check.

---

## 18. Error Handling and Edge Cases **[additions only; v1 table otherwise unchanged]**

| New/changed case | Detection | Behavior |
|---|---|---|
| Primary search provider fails/empty | Sec. 13 cascade | Automatic fallback to SerpApi, then optionally TinEye — no longer a hard stop |
| Chain unreachable during verification | RPC connection error at read time | `CHAIN_RPC_ERROR` — explicitly **not** silently resolved via the SQLite cache (Correction 4); user is told verification could not be completed |
| `recordId` never written | `getRecord().exists == false` | `RECORD_NOT_FOUND` (distinct from tamper — Correction 2) |
| Data can't be canonicalized at verify time | schema validation fails | `INSUFFICIENT_DATA` |
| Multiple faces in input image | >1 bbox from detector | **Default: auto-select the largest face by bounding-box area**, log all detected boxes and which was chosen (Correction 5) |
| Ambiguous top candidates (small margin) | top-1/top-2 similarity gap < margin | Auto-rejected as `LOW_CONFIDENCE_MATCH` in the default automatic flow (no human prompt); visible only in optional `--review` mode |

---

## 19. Security, Privacy and Secret Management **[unchanged from v1]**
Consented-input-only rule, minimal biometric retention, secret handling via env vars, `.gitignore` rules — all carried over unchanged.

---

## 20. Project Folder Structure **[REVISED — small additions]**

```
face-id-blockchain-verification/
├── ... (unchanged from v1) ...
├── pipeline/
│   ├── search/
│   │   ├── base.py                 # SearchProvider interface
│   │   ├── vision_search.py        # primary
│   │   ├── serpapi_search.py       # fallback
│   │   ├── tineye_search.py        # optional tertiary fallback  [NEW]
│   │   └── fetch_candidates.py
│   ├── canon/
│   │   └── canonicalize.py         # now splits immutable vs. audit fields  [REVISED]
│   ├── chain/
│   │   ├── writer.py               # submitRecord → returns recordId + tx hash  [REVISED]
│   │   └── reader.py               # getRecord(recordId)  [REVISED]
│   └── storage/
│       └── cache.py                # renamed from db.py — explicitly "cache," not a chain substitute  [RENAMED]
├── scripts/
│   ├── deploy_contract.py
│   └── calibrate_threshold.py      # threshold calibration tool  [NEW]
└── ...
```

---

## 22–23. Roadmap and Testing **[REVISED additions]**

**New/changed roadmap items:**
- Phase 3 now includes wiring all three search providers behind the cascade logic, not just one.
- Phase 4 now includes running `scripts/calibrate_threshold.py` against a real labeled set before locking in `SIMILARITY_THRESHOLD`.
- Phase 7 now includes the redesigned `recordId`-keyed contract and its deploy script.
- New Phase 8.5: **verification-logic regression tests** specifically for the tamper-vs-unknown distinction (see test matrix below).

**New/changed test cases:**

| Test Case | Input | Expected Result |
|---|---|---|
| Primary search provider simulated failure | invalid Vision credentials | Falls back to SerpApi automatically, pipeline still completes |
| Both primary+fallback empty | photo with no plausible online presence | `NO_MATCH`, no chain write attempted |
| Canonicalization stable across rediscovery | same live post, two separate pipeline runs (different timestamps) | Identical hash both times (Correction 3 regression test) |
| Verify with correct recordId, unmodified data | valid `recordId` + original canonical JSON | `VERIFIED` |
| Verify with correct recordId, modified data | valid `recordId` + 1 field changed | `TAMPER DETECTED` |
| **Verify with a `recordId` that was never written** | fabricated/unused `recordId` + arbitrary data | **`RECORD_NOT_FOUND`** (must not be `TAMPER DETECTED`) |
| Verify while chain RPC is down | valid `recordId`, RPC endpoint unreachable | `CHAIN_RPC_ERROR`, not a false `VERIFIED` from cache |
| Multiple faces in input | group photo | Largest face auto-selected, others logged, no prompt |
| Automatic matching with no human input | consented test photo | Best match selected end-to-end without any interactive prompt in default mode |
| Threshold calibration script | labeled pairs folder | Produces a threshold recommendation + genuine/impostor score summary |

---

## 25. End-to-End Demo Plan **[REVISED additions]**

Add to the recording script:
- After the search step, narrate which provider/representation produced the winning candidate (proves the cascade design is real, not just a slide).
- After the first VERIFIED/TAMPER DETECTED demonstration (unchanged from v1), add the **new** `RECORD_NOT_FOUND` case live: run `verify.py` with a `recordId` that was never submitted, showing it correctly returns `RECORD_NOT_FOUND` rather than being confused with tampering.
- State on camera that the gas token is POL and that funding came from a third-party faucet (Alchemy/QuickNode), since this differs from what most public tutorials still say.

---

## PRD REVISION SUMMARY

| # | Issue Identified | Why It Was a Problem | Exact Correction Made | Effect on Implementation |
|---|---|---|---|---|
| 1 | Search depended on a single provider (Google Vision) and a single image representation (face crop) | Reverse-image/web-detection APIs are general visual-similarity engines, not dedicated face search; a face crop alone often underperforms; one provider is a single point of failure | Added a defined cascade: primary (Google Vision) → fallback (SerpApi) → optional tertiary (TinEye), each queried with both the full image and a face crop as two representations (Sec. 13) | New `SearchProvider` implementations for SerpApi/TinEye; new representation-toggle env vars; pipeline logic now branches on provider/representation success |
| 2 | Verification looked up records by content hash, so tampered data and never-recorded data both produced "hash not found" | Made it structurally impossible to distinguish tampering from unrelated/unknown data — the single most important logical bug in v1 | Switched the on-chain schema to a sequential `recordId` key; verification is now `(recordId, data)` → reconstruct hash → compare against the *specific* record at that ID (Sec. 16C, 17) | Contract redesigned (`nextRecordId`, `getRecord(recordId)`); `writer.py`/`reader.py` signatures change; new regression test for `RECORD_NOT_FOUND` vs. `TAMPER DETECTED` |
| 3 | Discovery timestamp (and other run-specific values) were part of the hashed fingerprint | Rediscovering the same unmodified live post later would produce a different hash purely due to timestamp drift — a false "changed" signal | Split fields into Immutable Verifiable Data (hashed) vs. Audit/Run Metadata (stored, not hashed) (Sec. 15) | `canonicalize()` scope narrowed; new regression test confirming identical hash across two discovery runs of the same content |
| 4 | SQLite was presented as a possible fallback if blockchain RPC was unavailable | Local storage is not tamper-evident or independently verifiable; treating it as equivalent to a chain read would misrepresent the security guarantee | SQLite relabeled everywhere as a local metadata cache; if RPC is down, verification now returns an honest `CHAIN_RPC_ERROR` rather than silently trusting the cache (Sec. 16A) | `storage/db.py` renamed `storage/cache.py`; verification code path explicitly refuses to substitute cache for an on-chain read |
| 5 | Inconsistent handling of multiple detected faces across the document | No single defined default behavior risked inconsistent implementation and an unreliable/interactive demo | Standardized default: auto-select the largest face by bbox area, log all detections; manual selection is an explicit optional mode | `FACE_SELECTION_MODE` env var (`largest` default) |
| 6 | Human confirmation was implied as part of the main matching flow | Undermines the claim that the system itself performs matching; also risks an interactive step failing live on camera | Automatic threshold+margin selection is now the only default path; human review is a separate, clearly optional `--review` debugging mode, off by default | `MATCH_REVIEW_MODE` env var (`off` default); demo recording must not use review mode |
| 7 | Multiple plausible auth methods were mentioned per service without picking one | Ambiguity invites inconsistent implementation and setup confusion for a new developer | One documented primary auth method per service, with any alternate method explicitly noted as unsupported | Updated Environment Variable Specification (Sec. 9/10) |
| 8 | A specific similarity threshold (0.42) was presented as a fixed correct value | No universal threshold exists across models/datasets; presenting one as settled is misleading | Added a required calibration procedure and script using labeled consented pairs; threshold is documented as calibrated-and-limited, not universal | New `scripts/calibrate_threshold.py`; new deliverable `calibration_report.md` |
| 9 | Several cost/quota/pricing claims were stated as settled facts without clear sourcing, and one (Vision Web Detection pricing) was simply wrong | Presenting uncertain/incorrect figures as guaranteed risks budget surprises and broken assumptions during implementation | Re-researched claims; corrected the Web Detection price ($3.50/1,000 units, not $1.50); corrected Polygon's gas token name (POL) and faucet status (official faucet discontinued); explicitly flagged SerpApi/TinEye/Alchemy quota figures as needing a fresh check before implementation | New "facts requiring verification" table (Sec. 9/10); README must link directly to each provider's live pricing/docs page rather than quoting fixed numbers as permanent |

---

## FINAL CORRECTED ARCHITECTURE

```
INPUT IMAGE
   ↓ validate (format/size)
FACE DETECTION (InsightFace, dlib fallback)
   ↓ multiple faces? → auto-select largest, log all (default; manual mode optional)
FACE QUALITY VALIDATION (blur, size, single selected face)
   ↓
FACE EMBEDDING (ArcFace 512-d, dlib 128-d fallback)
   ↓
SEARCH REPRESENTATIONS PREPARED: [full image, padded face crop]
   ↓
PRIMARY SEARCH: Google Cloud Vision Web Detection (both representations)
   ↓ (on provider error or zero candidates)
FALLBACK SEARCH: SerpApi Google Lens (both representations)
   ↓ (optional, if still zero candidates)
TERTIARY FALLBACK: TinEye API (full image only)
   ↓
DYNAMIC CANDIDATE DISCOVERY — merge + dedupe across whichever provider(s) ran
   ↓
CANDIDATE COLLECTION — live fetch of each candidate page
   ↓
FACE VALIDATION — original embedding vs. every candidate image, cosine similarity
   ↓
AUTOMATIC BEST-MATCH SELECTION — threshold (calibrated, Sec. 14) + margin, no human step
   (optional --review debug mode exists outside this default flow)
   ↓
POST DATA EXTRACTION
   ↓
CANONICAL DATA SPLIT:
   ├── Immutable Verifiable Data → hashed (SHA-256) → becomes the on-chain content hash
   └── Audit/Run Metadata → stored in local cache only, never hashed
   ↓
BLOCKCHAIN WRITE — submitRecord(contentHash, metadataURI) on Polygon Amoy testnet
   (funded via a third-party faucet; gas token is POL)
   ↓
STABLE IDENTIFIER RETURNED — recordId (+ tx hash), stored in local cache (a cache, not a
   verification source)
   ↓
   ... time passes, possibly a long time ...
   ↓
INDEPENDENT RE-VERIFICATION — input (recordId, data_to_verify), run as a fully separate process:
   1. Canonicalize data_to_verify → if impossible: INSUFFICIENT_DATA
   2. Recompute hash
   3. getRecord(recordId) on-chain, read-only
      → not found: RECORD_NOT_FOUND
   4. Compare recomputed hash to the on-chain hash for that specific recordId
      → mismatch: TAMPER DETECTED
      → match: continue
   5. (Optional) live-check the source URL
      → unreachable: SOURCE_UNAVAILABLE
      → reachable: VERIFIED
   (If the chain RPC itself is unreachable during this process: CHAIN_RPC_ERROR — never silently
   answered from the local cache.)

FALLBACK BLOCKCHAIN (demo-safety only, clearly labeled as non-public): local Hardhat node running
   the identical contract, toggled via USE_LOCAL_CHAIN=true.
```

This is the architecture to build against. Section numbers throughout this document map onto v1's structure; any section not explicitly marked **[REVISED]** above carries over from v1 unchanged.
