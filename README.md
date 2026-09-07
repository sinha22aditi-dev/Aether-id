# Face ID + Blockchain Verification Pipeline (AETHER-ID)
## HH Goa 2026 — Task #3: Biometric Web Discovery & Immutable On-Chain Ledger

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Solidity 0.8.20](https://img.shields.io/badge/Solidity-0.8.20-363636?logo=solidity&logoColor=white)](https://soliditylang.org/)
[![Polygon Amoy](https://img.shields.io/badge/Network-Polygon_Amoy_(80002)-8247E5?logo=polygon&logoColor=white)](https://amoy.polygonscan.com/)
[![Tests](https://img.shields.io/badge/pytest-36%20passed-10B981?logo=pytest&logoColor=white)](tests/)

---

## 1. Ethical Framing & Consent Requirement
> [!IMPORTANT]
> **Consented Input Only:** This pipeline is strictly engineered to search and verify faces where explicit operator or subject consent has been granted. It is designed for authentic identity attribution, intellectual property provenance, and tamper detection.

---

## 2. Executive Summary & Core Pipeline
AETHER-ID is a genuinely autonomous, multi-stage pipeline connecting state-of-the-art computer vision, multi-provider web search cascades, biometric validation, two-tier cryptographic canonicalization, and Ethereum Virtual Machine (EVM) smart contracts.

```
INPUT IMAGE
   ↓ Format/Dimension validation
FACE DETECTION (MTCNN + OpenCV Haar Fallback)
   ↓ Auto-selects largest face by area (logs all detected bboxes)
FACE QUALITY VALIDATION (Laplacian blur variance, minimum dimensions)
   ↓
FACE EMBEDDING (InceptionResnetV1 / FaceNet 512-d L2-normalized vector)
   ↓
SEARCH REPRESENTATIONS:
   ├── Representation A: Full Original Image (scene, clothing, background context)
   └── Representation B: Padded Face Crop (+20% margin around bbox)
   ↓
DYNAMIC SEARCH CASCADE:
   ├── Primary: Google AI Studio Gemini API with Search Grounding (Representation A & B)
   ├── Fallback: SerpApi Google Lens (Representation A & B)
   └── Tertiary: TinEye API (Representation A)
   ↓
DYNAMIC CANDIDATE DISCOVERY: Merge & deduplicate candidates across active engines
   ↓
CANDIDATE COLLECTION: Live page fetch (httpx + BeautifulSoup) & media extraction
   ↓
BIOMETRIC VALIDATION: Candidate face embeddings vs. ORIGINAL face embedding (cosine similarity)
   ↓
AUTOMATIC BEST-MATCH SELECTION: Calibrated threshold + margin check (no human prompt in default flow)
   ↓
DATA EXTRACTION: Platform, URL, Post ID, clean text, image bytes SHA-256
   ↓
TWO-TIER DATA MODEL SPLIT:
   ├── Immutable Verifiable Data → Deterministic JSON → SHA-256 → contentHash (bytes32)
   └── Audit/Run Metadata → Saved to SQLite cache only (never hashed)
   ↓
BLOCKCHAIN COMMITMENT: FaceMatchRegistry.submitRecord(contentHash, metadataURI) on Polygon Amoy
   ↓ Returns sequential recordId + transaction hash
LOCAL CACHE STORAGE: Saved to SQLite (a cache/audit log, never a verification substitute)
   ↓
INDEPENDENT RE-VERIFICATION (recordId, data):
   1. Canonicalize data → if invalid: INSUFFICIENT_DATA
   2. Compute new_hash = SHA256(canonical_bytes)
   3. Call getRecord(recordId) on-chain
      → if not found (exists=false): RECORD_NOT_FOUND
   4. Compare new_hash == on_chain_contentHash
      → if mismatch: TAMPER DETECTED (with field diff)
      → if match: continue
   5. Live source URL check
      → if unreachable: SOURCE_UNAVAILABLE
      → if reachable: VERIFIED
   (If blockchain RPC is down: CHAIN_RPC_ERROR — refuses to substitute local cache)
```

---

## 3. PRD v2 Architectural Corrections Implemented

| # | PRD Correction | Implementation Guarantee |
|---|---|---|
| # | PRD Correction | Implementation Guarantee |
|---|---|---|
| **1** | **Multi-Provider & Multi-Representation Search** | Cascade across Google AI Studio Gemini, SerpApi, and TinEye using both Full Scene Context and Padded Face Crops. No single point of failure. |
| **2** | **Record ID Keying vs Hash Lookup** | Smart contract (`FaceMatchRegistry.sol`) keys records by sequential `recordId`. Distinguishes `TAMPER DETECTED` from `RECORD_NOT_FOUND`. |
| **3** | **Two-Tier Canonicalization** | Separates Immutable Verifiable Data (hashed) from Audit Metadata (off-chain). Re-discovering the same live post produces the exact same hash across time. |
| **4** | **SQLite Local Storage as Cache** | SQLite explicitly labeled as cache/audit log. If RPC is down, returns `CHAIN_RPC_ERROR` rather than silently trusting local cache. |
| **5** | **Multiple Faces Standardized** | Defaults to largest face by bounding box area (`FACE_SELECTION_MODE="largest"`). |
| **6** | **Autonomous Matching** | Calibrated threshold + margin filter makes match decisions automatically without interactive human prompts (human review is an optional `--review` flag). |
| **7** | **Standardized Auth** | Bearer API Keys (`GEMINI_API_KEY`, `SERPAPI_KEY`); HMAC signature for TinEye; ECDSA private key for wallet. |
| **8** | **Threshold Calibration** | Provided `scripts/calibrate_threshold.py` script and generated `calibration_report.md`. |
| **9** | **Polygon Amoy POL Token & Faucets** | Target is Polygon Amoy (Chain ID 80002) with native gas token **POL** (formerly MATIC) funded via third-party faucets. |

---

## 4. Setup & Installation

### Prerequisites
- Python 3.11+
- Git

### 1. Clone & Install Dependencies
```bash
# Clone repository
git clone https://github.com/your-username/face-id-blockchain-verification.git
cd face-id-blockchain-verification

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

```ini
# Primary Search: Google AI Studio Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Fallback Search: SerpApi
SERPAPI_KEY=your_serpapi_key_here

# Tertiary Fallback: TinEye (Optional)
TINEYE_API_KEY=your_tineye_key
TINEYE_API_SECRET=your_tineye_secret

# Blockchain Configuration (Polygon Amoy Testnet)
# Dedicated Authenticated RPC (Recommended):
#   Alchemy: https://polygon-amoy.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
#   Infura:  https://polygon-amoy.infura.io/v3/YOUR_INFURA_KEY
# Reliable Public Fallback:
BLOCKCHAIN_RPC_URL=https://polygon-amoy.drpc.org
CHAIN_ID=80002
WALLET_PRIVATE_KEY=your_private_key_here
CONTRACT_ADDRESS=0xF2E246BB76DF876Cef8b38ae84130F4F55De395b

# Offline / Local EVM Testing Toggle (Explicit demo/testing mode)
USE_LOCAL_CHAIN=false
```

---

## 5. Polygon Amoy Testnet, Dedicated RPC & Faucet Instructions

### Dedicated Authenticated RPC Providers (Recommended)
Public RPC endpoints can experience transient rate limits or DNS downtime. For production reliability, use a dedicated RPC provider endpoint in `BLOCKCHAIN_RPC_URL`:
- **Alchemy:** Create a free app on [Alchemy](https://www.alchemy.com/) for Polygon Amoy -> `https://polygon-amoy.g.alchemy.com/v2/YOUR_API_KEY`
- **Infura:** Create a free project on [Infura](https://www.infura.io/) for Polygon Amoy -> `https://polygon-amoy.infura.io/v3/YOUR_API_KEY`
- **dRPC (Public/Dedicated):** [https://drpc.org/](https://drpc.org/) -> `https://polygon-amoy.drpc.org`
- **PublicNode:** `https://polygon-amoy-bor-rpc.publicnode.com`

### Amoy Testnet Faucets (POL Gas Tokens)
Obtain testnet **POL** tokens for Polygon Amoy (Chain ID 80002) using these verified faucets:
1. **Polygon Official Faucet:** [https://faucet.polygon.technology/](https://faucet.polygon.technology/)
2. **Alchemy Polygon Amoy Faucet:** [https://www.alchemy.com/faucets/polygon-amoy](https://www.alchemy.com/faucets/polygon-amoy)
3. **Chainlink Faucets:** [https://faucets.chain.link/polygon-amoy](https://faucets.chain.link/polygon-amoy)

---

## 6. Smart Contract Deployment & Diagnostics

### Deploying the FaceMatchRegistry Contract
Deploy the universal Solidity 0.8.20 smart contract with one command:
```bash
# Deploy to Polygon Amoy (requires WALLET_PRIVATE_KEY with POL balance)
python scripts/deploy_contract.py

# Or deploy to in-process local EVM for offline testing
python scripts/deploy_contract.py --local
```

### Startup Diagnostics & Error Categorization
The system performs automated diagnostic health checks on startup and before each write:
| Error Condition | Specific Exception | Diagnostic Action & Remediation |
| :--- | :--- | :--- |
| **RPC Unreachable / DNS Fail** | `ChainRPCUnreachableError` | Reports endpoint failure; check internet or supply dedicated Alchemy/Infura RPC in `BLOCKCHAIN_RPC_URL`. |
| **Chain ID Mismatch** | `ChainIDMismatchError` | RPC network mismatch (e.g. returned Mainnet 1 instead of Amoy 80002). |
| **Missing Wallet Key** | `WalletNotConfiguredError` | Missing/placeholder `WALLET_PRIVATE_KEY`. Set valid key or use `USE_LOCAL_CHAIN=true`. |
| **Invalid Key Format** | `InvalidWalletKeyError` | Key is not 64 hex characters (32 bytes). |
| **Insufficient Gas Balance** | `InsufficientFundsError` | Wallet has 0 or low POL. Prompts with faucet URLs to obtain free testnet POL. |
| **Missing Contract** | `ContractNotConfiguredError` | `CONTRACT_ADDRESS` not set in `.env`. Run `python scripts/deploy_contract.py`. |
| **No Deployed Bytecode** | `ContractNotDeployedError` | Target address has no bytecode on-chain. Run deployment script on active network. |

To deploy a fresh `FaceMatchRegistry` contract to Polygon Amoy:
```bash
python scripts/deploy_contract.py
```

---

## 6. Running the Pipeline (CLI)

### Autonomous Scan & On-Chain Registration
```bash
# Run scan on a consented portrait
python main.py --image path/to/consented_photo.jpg

# Run scan on a group photo with a specific face index
python main.py --image path/to/group.jpg --face-index 0

# Run in dry-run mode (simulates pipeline without blockchain write)
python main.py --image path/to/photo.png --dry-run

# Run with optional human review mode
python main.py --image path/to/photo.png --review
```

---

## 7. Independent Verification Tool (`verify.py`)

Independent verification evaluates 6 distinct status outcomes without relying on local storage:

```bash
# 1. VERIFIED: Original data verified against on-chain record #0
python verify.py --record-id 0 --from-cache

# 2. Verify using explicit JSON payload
python verify.py --record-id 0 --canonical-json ./payload.json

# 3. RECORD_NOT_FOUND: Verifying uncommitted record ID #99999
python verify.py --record-id 99999 --canonical-json ./payload.json
```

### Live Tamper Demonstration
Run the automated demonstration script to observe all 3 core states live on a real EVM ledger:
```bash
python scripts/test_tamper.py
```

---

## 8. Web Dashboard & Interactive UI

Start the local FastAPI web server:
```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000 --reload
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser to access:
- **Scan & Discovery Pipeline:** Webcam snap, drag-and-drop file upload, real-time step telemetry, candidate match gallery, two-tier JSON view.
- **Independent Verification Sandbox:** On-chain verification tester, live tamper injection simulator, field diff visualizer.
- **Ledger Explorer:** Table of cached records with one-click verification shortcuts.
- **Architecture & PRD Specifications:** Interactive workflow diagram and PRD v2 correction breakdown.

---

## 9. Running Automated Tests

Run the complete 27-test suite covering face detection, blur validation, embedding normalization, cosine similarity, search cascade fallback, canonicalization invariance, real EVM contract execution, and all 6 verification outcomes:

```bash
python -m pytest tests/ -v
```

---

## 10. External Services Pricing & Quotas

| Service | Feature | Auth Method | Pricing / Free Tier | Link |
|---|---|---|---|---|
| **Google AI Studio (Gemini)** | Visual Discovery & Search Grounding | Bearer API Key | Free Tier available (15 RPM / 1M TPM on Flash) | [AI Studio Pricing](https://ai.google.dev/pricing) |
| **SerpApi** | Google Lens Engine | Bearer API Key | 100 free searches/month on free plan | [Pricing Page](https://serpapi.com/pricing) |
| **TinEye API** | Reverse Search | API Key + Secret (HMAC) | Commercial plans starting at $200 for 5,000 searches | [Pricing Page](https://services.tineye.com/TinEyeAPI) |
| **Polygon Amoy** | EVM Smart Contract | ECDSA Private Key | Free (Testnet POL) | [Polygon Documentation](https://docs.polygon.technology/) |

---

## 11. Repository Structure

```
face-id-blockchain-verification/
├── contracts/
│   └── FaceMatchRegistry.sol       # Solidity 0.8.20 recordId-keyed contract
├── pipeline/
│   ├── face/
│   │   ├── detector.py             # MTCNN & OpenCV detection, blur check, largest face select
│   │   └── embedder.py             # InceptionResnetV1 512-d L2-normalized embeddings
│   ├── search/
│   │   ├── base.py                 # SearchProvider interface
│   │   ├── representations.py      # Full Image (A) & Padded Face Crop (B) builders
│   │   ├── gemini_search.py        # Primary Google AI Studio Gemini Search Grounding
│   │   ├── serpapi_search.py       # Fallback SerpApi Google Lens
│   │   ├── tineye_search.py        # Tertiary TinEye API
│   │   ├── cascade.py              # Multi-provider cascade orchestrator & deduplicator
│   │   └── fetch_candidates.py     # Live HTTP page scraper & media downloader
│   ├── match/
│   │   ├── matcher.py              # Candidate scoring, calibrated threshold & margin filter
│   │   └── extractor.py            # Structured post metadata extraction & pHash
│   ├── canon/
│   │   └── canonicalize.py         # Two-tier split & SHA-256 fingerprinting
│   ├── chain/
│   │   ├── abi.py                  # Compiled bytecode & ABI
│   │   ├── client.py               # Web3 client for Polygon Amoy & Local EVM
│   │   ├── writer.py               # submitRecord transaction creator & event parser
│   │   └── reader.py               # getRecord on-chain reader
│   ├── storage/
│   │   └── cache.py                # SQLite local cache and audit trail
│   ├── verifier.py                 # 6-outcome independent verification engine
│   └── pipeline.py                 # End-to-end pipeline orchestrator
├── scripts/
│   ├── deploy_contract.py          # Contract deployer
│   ├── calibrate_threshold.py      # Biometric threshold calibration tool
│   └── test_tamper.py              # Live tampering & verification demonstration
├── server/
│   ├── app.py                      # FastAPI web backend
│   └── static/
│       ├── index.html              # Modern glassmorphism UI
│       ├── style.css               # Vanilla CSS styling
│       └── app.js                  # Frontend interactive controller
├── tests/
│   ├── test_face.py                # Face detection, blur, and embedder tests
│   ├── test_search.py              # Search representations & cascade fallback tests
│   ├── test_matcher.py             # Automatic threshold & margin decision tests
│   ├── test_canonicalize.py        # Idempotence & multi-run invariance regression tests
│   ├── test_blockchain.py          # Real EVM contract deployment, write, and read tests
│   └── test_verify.py              # All 6 verification status codes tests
├── main.py                         # CLI pipeline entry point
├── verify.py                       # CLI independent verification tool
├── PRD.md                          # Master PRD specification
├── PROJECT_HANDOVER.md             # Project state & handover notes
├── TODO.md                         # Task roadmap & status checklist
├── calibration_report.md           # Biometric threshold sweep report
├── .env.example                    # Environment configuration template
├── .gitignore                      # Git ignore patterns
└── requirements.txt                # Dependency manifest
```
