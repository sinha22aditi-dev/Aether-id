"""
Independent Re-Verification Engine.
Implements the 6-state verification architecture from PRD Section 17:
1. VERIFIED
2. TAMPER DETECTED
3. RECORD_NOT_FOUND
4. INSUFFICIENT_DATA
5. SOURCE_UNAVAILABLE
6. CHAIN_RPC_ERROR
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from pipeline.canon.canonicalize import Canonicalizer, ImmutableVerifiableData
from pipeline.chain.client import BlockchainClient, ChainRPCError
from pipeline.chain.reader import BlockchainReader, OnChainRecord
from pipeline.storage.cache import MetadataCache

logger = logging.getLogger("pipeline.verifier")


@dataclass
class FieldDiff:
    """Represents a discrepancy between verified data and original recorded data."""
    field_name: str
    original_value: Any
    tampered_value: Any


@dataclass
class VerificationResult:
    """Detailed result of independent verification."""
    status: str                         # VERIFIED | TAMPER DETECTED | RECORD_NOT_FOUND | INSUFFICIENT_DATA | SOURCE_UNAVAILABLE | CHAIN_RPC_ERROR
    record_id: int
    computed_hash: Optional[str] = None
    on_chain_hash: Optional[str] = None
    on_chain_record: Optional[OnChainRecord] = None
    is_hash_match: bool = False
    source_url_reachable: bool = False
    field_diffs: List[FieldDiff] = field(default_factory=list)
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")


class RecordVerifier:
    """
    Independent verification engine.
    Given (recordId, data_to_verify), retrieves on-chain record and verifies data integrity.
    """

    def __init__(
        self,
        reader: Optional[BlockchainReader] = None,
        cache: Optional[MetadataCache] = None,
        check_live_source: bool = True,
        http_timeout: float = 6.0,
    ):
        self.reader = reader or BlockchainReader()
        self.cache = cache or MetadataCache()
        self.check_live_source = check_live_source
        self.http_timeout = http_timeout

    def _check_source_url(self, url: str) -> bool:
        """Performs a live HTTP GET / HEAD request to verify source availability."""
        if not url or not url.startswith(("http://", "https://")):
            return False
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VerificationBot/1.0"}
            with httpx.Client(timeout=self.http_timeout, follow_redirects=True, headers=headers) as client:
                resp = client.get(url)
                return resp.status_code < 400
        except Exception as e:
            logger.debug(f"Live source URL check failed for {url}: {e}")
            return False

    def _generate_diff(
        self,
        supplied_data: Dict[str, Any],
        cached_data: Dict[str, Any],
    ) -> List[FieldDiff]:
        """Generates human-readable field-level differences for diagnostic display."""
        diffs = []
        all_keys = set(supplied_data.keys()).union(set(cached_data.keys()))
        for k in sorted(all_keys):
            v_orig = cached_data.get(k)
            v_supp = supplied_data.get(k)
            if v_orig != v_supp:
                diffs.append(
                    FieldDiff(
                        field_name=k,
                        original_value=v_orig,
                        tampered_value=v_supp,
                    )
                )
        return diffs

    def verify(
        self,
        record_id: int,
        data_to_verify: Dict[str, Any],
    ) -> VerificationResult:
        """
        Executes full 5-step verification process per PRD Section 17.
        """
        logger.info(f"==> Initiating Independent Verification for Record #{record_id}...")

        # Step 1: Attempt to canonicalize supplied data
        try:
            canonical_bytes = Canonicalizer.canonicalize_dict(data_to_verify)
            computed_hash = Canonicalizer.compute_sha256_hash(canonical_bytes)
        except Exception as e:
            logger.warning(f"Verification aborted: supplied data failed schema validation ({e}).")
            return VerificationResult(
                status="INSUFFICIENT_DATA",
                record_id=record_id,
                message=f"Supplied data is missing mandatory immutable fields: {e}",
            )

        # Step 2: Read on-chain record via getRecord(recordId)
        try:
            on_chain_rec = self.reader.get_record(record_id)
        except ChainRPCError as e:
            logger.error(f"Verification aborted: blockchain RPC unreachable ({e}).")
            return VerificationResult(
                status="CHAIN_RPC_ERROR",
                record_id=record_id,
                computed_hash=computed_hash,
                message=f"Cannot verify: Blockchain RPC endpoint is unreachable ({e}). Local cache is NOT an authoritative substitute.",
            )
        except Exception as e:
            logger.error(f"Blockchain read error: {e}")
            return VerificationResult(
                status="CHAIN_RPC_ERROR",
                record_id=record_id,
                computed_hash=computed_hash,
                message=f"Blockchain read error: {e}",
            )

        # Step 3: Check if record exists on-chain
        if not on_chain_rec.exists:
            logger.warning(f"Record #{record_id} does NOT exist on-chain (exists=false).")
            return VerificationResult(
                status="RECORD_NOT_FOUND",
                record_id=record_id,
                computed_hash=computed_hash,
                on_chain_record=on_chain_rec,
                message=f"Record #{record_id} was never written to the blockchain registry.",
            )

        # Step 4: Compare computed hash with on-chain contentHash
        on_chain_hash = on_chain_rec.content_hash
        is_match = computed_hash.lower() == on_chain_hash.lower()

        # Check for field diffs against cached original if available
        cached_rec = self.cache.get_record(record_id)
        diffs = []
        if not is_match and cached_rec:
            diffs = self._generate_diff(data_to_verify, cached_rec.immutable_data)

        if not is_match:
            logger.warning(
                f"TAMPER DETECTED on Record #{record_id}! "
                f"Computed: {computed_hash[:12]}... != On-Chain: {on_chain_hash[:12]}..."
            )
            return VerificationResult(
                status="TAMPER DETECTED",
                record_id=record_id,
                computed_hash=computed_hash,
                on_chain_hash=on_chain_hash,
                on_chain_record=on_chain_rec,
                is_hash_match=False,
                field_diffs=diffs,
                message=(
                    f"Cryptographic hash mismatch for Record #{record_id}. "
                    "The supplied data has been altered since the original blockchain commitment."
                ),
            )

        # Step 5: Hash matches! Check live source URL availability
        source_url = data_to_verify.get("normalized_source_url", "")
        source_ok = True
        if self.check_live_source and source_url:
            source_ok = self._check_source_url(source_url)

        if not source_ok:
            logger.info(
                f"Record #{record_id} hash verified on-chain, but live source URL is unreachable."
            )
            return VerificationResult(
                status="SOURCE_UNAVAILABLE",
                record_id=record_id,
                computed_hash=computed_hash,
                on_chain_hash=on_chain_hash,
                on_chain_record=on_chain_rec,
                is_hash_match=True,
                source_url_reachable=False,
                message=(
                    f"Integrity verified on-chain, but the live source at '{source_url}' is currently unreachable."
                ),
            )

        logger.info(f"==> Record #{record_id} FULLY VERIFIED on-chain!")
        return VerificationResult(
            status="VERIFIED",
            record_id=record_id,
            computed_hash=computed_hash,
            on_chain_hash=on_chain_hash,
            on_chain_record=on_chain_rec,
            is_hash_match=True,
            source_url_reachable=True,
            message=f"Record #{record_id} successfully verified on-chain. Data integrity intact.",
        )
