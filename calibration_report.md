# Biometric Threshold Calibration Report
**Generated:** 2026-09-05T19:01:28.874752Z  
**Model:** `facenet-inceptionresnetv1-vggface2-512d`  
**Dataset:** Consented Calibration Pairs (10 Genuine pairs, 10 Impostor pairs)

---

## 1. Summary Statistics
- **Recommended Threshold (`SIMILARITY_THRESHOLD`):** `0.88`
- **Recommended Margin (`MATCH_CONFIDENCE_MARGIN`):** `0.05`
- **Genuine Pair Score Mean:** `0.9610` (Min: `0.8703`, Max: `0.9975`)
- **Impostor Pair Score Mean:** `0.6609` (Min: `0.5044`, Max: `0.8747`)

---

## 2. Threshold Calibration Sweep Matrix

| Threshold | False Accept Rate (FAR) | False Reject Rate (FRR) | Total Error |
|:---------:|:-----------------------:|:-----------------------:|:-----------:|
| 0.40 | 100.0% | 0.0% | 100.0% |
| 0.42 | 100.0% | 0.0% | 100.0% |
| 0.44 | 100.0% | 0.0% | 100.0% |
| 0.46 | 100.0% | 0.0% | 100.0% |
| 0.48 | 100.0% | 0.0% | 100.0% |
| 0.50 | 100.0% | 0.0% | 100.0% |
| 0.52 | 90.0% | 0.0% | 90.0% |
| 0.54 | 80.0% | 0.0% | 80.0% |
| 0.56 | 80.0% | 0.0% | 80.0% |
| 0.58 | 80.0% | 0.0% | 80.0% |
| 0.60 | 70.0% | 0.0% | 70.0% |
| 0.62 | 40.0% | 0.0% | 40.0% |
| 0.64 | 40.0% | 0.0% | 40.0% |
| 0.66 | 30.0% | 0.0% | 30.0% |
| 0.68 | 30.0% | 0.0% | 30.0% |
| 0.70 | 30.0% | 0.0% | 30.0% |
| 0.72 | 30.0% | 0.0% | 30.0% |
| 0.74 | 30.0% | 0.0% | 30.0% |
| 0.76 | 30.0% | 0.0% | 30.0% |
| 0.78 | 30.0% | 0.0% | 30.0% |
| 0.80 | 30.0% | 0.0% | 30.0% |
| 0.82 | 20.0% | 0.0% | 20.0% |
| 0.84 | 20.0% | 0.0% | 20.0% |
| 0.86 | 10.0% | 0.0% | 10.0% |
| **0.88** | 0.0% | 10.0% | 10.0% |

---

## 3. Methodological Justification
Per PRD Section 14 (Correction 8), biometric similarity thresholds cannot be assumed as static magic numbers across models. 
For blockchain identity logging, a **False Accept (FAR)** is the critical failure mode, as it commits an incorrect identity match to an immutable public ledger. The selected threshold minimizes FAR while maintaining high recall for authentic genuine pairs.
