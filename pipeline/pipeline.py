"""
End-to-End Orchestrated Pipeline Runner.
Connects Computer Vision, Multi-Provider Search Cascade, Biometric Matching,
Two-Tier Canonicalization, Smart Contract Writes, and Local Caching.
"""

from dataclasses import dataclass, field
import datetime
import io
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
from PIL import Image

from pipeline.canon.canonicalize import (
    AuditMetadata,
    Canonicalizer,
    ImmutableVerifiableData,
)
from pipeline.chain.client import BlockchainClient
from pipeline.chain.writer import BlockchainWriter, WriteReceipt
from pipeline.face.detector import FaceDetectionResult, FaceDetector
from pipeline.face.embedder import FaceEmbedder
from pipeline.match.extractor import ExtractedPostData, PostDataExtractor
from pipeline.match.matcher import BiometricMatcher, MatchDecision, ScoredCandidate
from pipeline.search.base import SearchResult
from pipeline.search.cascade import CascadeResult, SearchCascade
from pipeline.search.fetch_candidates import CandidateFetcher, FetchedCandidate
from pipeline.search.representations import RepresentationBuilder, SearchRepresentations
from pipeline.storage.cache import CachedRecord, MetadataCache

logger = logging.getLogger("pipeline.orchestrator")


@dataclass
class PipelineStepLog:
    """Telemetry log for an individual pipeline step."""
    step_name: str
    status: str                         # SUCCESS | WARNING | FAILED | SKIPPED
    duration_ms: int
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineExecutionResult:
    """Comprehensive output of an end-to-end pipeline run."""
    status: str                         # SUCCESS | NO_FACE_DETECTED | FACE_TOO_SMALL | NO_MATCH | LOW_CONFIDENCE_MATCH | SEARCH_PROVIDER_UNAVAILABLE | CHAIN_WRITE_ERROR
    detection: Optional[FaceDetectionResult] = None
    cascade: Optional[CascadeResult] = None
    fetched_candidates: List[FetchedCandidate] = field(default_factory=list)
    match_decision: Optional[MatchDecision] = None
    extracted_data: Optional[ExtractedPostData] = None
    immutable_data: Optional[ImmutableVerifiableData] = None
    audit_metadata: Optional[AuditMetadata] = None
    content_hash: Optional[str] = None
    write_receipt: Optional[WriteReceipt] = None
    cached_record: Optional[CachedRecord] = None
    logs: List[PipelineStepLog] = field(default_factory=list)
    total_duration_ms: int = 0
    error_message: Optional[str] = None


class VerificationPipeline:
    """
    Primary Orchestrator for Face ID + Blockchain Verification.
    """

    def __init__(
        self,
        detector: Optional[FaceDetector] = None,
        embedder: Optional[FaceEmbedder] = None,
        cascade: Optional[SearchCascade] = None,
        fetcher: Optional[CandidateFetcher] = None,
        matcher: Optional[BiometricMatcher] = None,
        writer: Optional[BlockchainWriter] = None,
        cache: Optional[MetadataCache] = None,
        similarity_threshold: Optional[float] = None,
        confidence_margin: Optional[float] = None,
    ):
        self.detector = detector or FaceDetector(
            selection_mode=os.getenv("FACE_SELECTION_MODE", "largest"),
            min_face_size=int(os.getenv("FACE_MIN_SIZE", "80")),
            blur_threshold=float(os.getenv("FACE_BLUR_THRESHOLD", "60.0")),
        )
        self.embedder = embedder or FaceEmbedder()
        self.cascade = cascade or SearchCascade()
        self.fetcher = fetcher or CandidateFetcher()

        sim_thresh = similarity_threshold or float(os.getenv("SIMILARITY_THRESHOLD", "0.60"))
        conf_margin = confidence_margin or float(os.getenv("MATCH_CONFIDENCE_MARGIN", "0.05"))
        self.matcher = matcher or BiometricMatcher(
            similarity_threshold=sim_thresh,
            confidence_margin=conf_margin,
            detector=FaceDetector(
                selection_mode="largest",
                min_face_size=35,
                blur_threshold=15.0,
            ),
            embedder=self.embedder,
        )

        self.writer = writer or BlockchainWriter()
        self.cache = cache or MetadataCache()
        self.rep_builder = RepresentationBuilder(
            use_full_image=os.getenv("SEARCH_USE_FULL_IMAGE", "true").lower() == "true",
            use_face_crop=os.getenv("SEARCH_USE_FACE_CROP", "true").lower() == "true",
        )

    @property
    def chain_client(self) -> BlockchainClient:
        return self.writer.client

    def run(
        self,
        image_input: Union[str, bytes, Image.Image, np.ndarray],
        force_face_index: Optional[int] = None,
        review_callback: Optional[Callable[[MatchDecision], bool]] = None,
        skip_blockchain: bool = False,
    ) -> PipelineExecutionResult:
        """
        Executes complete pipeline flow from input image to blockchain commitment.
        """
        start_time = time.time()
        step_logs: List[PipelineStepLog] = []

        logger.info("=================================================================")
        logger.info("Starting Face ID + Blockchain Verification Pipeline Run")
        logger.info("=================================================================")

        # ----------------------------------------------------------------------
        # Step 1: Face Detection & Quality Validation
        # ----------------------------------------------------------------------
        t0 = time.time()
        det_result = self.detector.detect(image_input, force_index=force_face_index)
        elapsed_det = int((time.time() - t0) * 1000)

        if not det_result.success:
            step_logs.append(
                PipelineStepLog(
                    step_name="face_detection",
                    status="FAILED",
                    duration_ms=elapsed_det,
                    details={"error": det_result.error_message, "total_faces": det_result.total_faces},
                )
            )
            return PipelineExecutionResult(
                status=det_result.error_message or "NO_FACE_DETECTED",
                detection=det_result,
                logs=step_logs,
                total_duration_ms=int((time.time() - start_time) * 1000),
                error_message=det_result.error_message,
            )

        step_logs.append(
            PipelineStepLog(
                step_name="face_detection",
                status="SUCCESS",
                duration_ms=elapsed_det,
                details={
                    "total_faces": det_result.total_faces,
                    "selected_index": det_result.selected_index,
                    "box": det_result.box,
                    "blur_score": det_result.blur_score,
                    "is_blurry": det_result.is_blurry,
                },
            )
        )

        # ----------------------------------------------------------------------
        # Step 2: Biometric Embedding Extraction
        # ----------------------------------------------------------------------
        t0 = time.time()
        orig_embedding = self.embedder.get_embedding(det_result.crop_image)
        elapsed_emb = int((time.time() - t0) * 1000)
        step_logs.append(
            PipelineStepLog(
                step_name="face_embedding",
                status="SUCCESS",
                duration_ms=elapsed_emb,
                details={"embedding_dim": len(orig_embedding), "model": self.embedder.model_version},
            )
        )

        # ----------------------------------------------------------------------
        # Step 3: Search Representations Preparation
        # ----------------------------------------------------------------------
        t0 = time.time()
        representations = self.rep_builder.build(image_input, face_box=det_result.box)
        elapsed_rep = int((time.time() - t0) * 1000)
        step_logs.append(
            PipelineStepLog(
                step_name="representation_builder",
                status="SUCCESS",
                duration_ms=elapsed_rep,
                details={
                    "full_image_bytes": len(representations.full_image_bytes) if representations.full_image_bytes else 0,
                    "face_crop_bytes": len(representations.face_crop_bytes) if representations.face_crop_bytes else 0,
                },
            )
        )

        # ----------------------------------------------------------------------
        # Step 4: Multi-Provider Search Cascade
        # ----------------------------------------------------------------------
        t0 = time.time()
        cascade_res = self.cascade.run(representations)
        elapsed_search = int((time.time() - t0) * 1000)

        step_logs.append(
            PipelineStepLog(
                step_name="search_cascade",
                status="SUCCESS" if cascade_res.status == "SUCCESS" else "FAILED",
                duration_ms=elapsed_search,
                details={
                    "status": cascade_res.status,
                    "winning_provider": cascade_res.winning_provider,
                    "winning_representation": cascade_res.winning_representation,
                    "candidate_count": len(cascade_res.candidates),
                },
            )
        )

        if cascade_res.status != "SUCCESS" or len(cascade_res.candidates) == 0:
            return PipelineExecutionResult(
                status=cascade_res.status,
                detection=det_result,
                cascade=cascade_res,
                logs=step_logs,
                total_duration_ms=int((time.time() - start_time) * 1000),
                error_message=f"Search cascade terminated with status: {cascade_res.status}",
            )

        # ----------------------------------------------------------------------
        # Step 5: Candidate Page Fetching & Image Extraction
        # ----------------------------------------------------------------------
        t0 = time.time()
        fetched_cands = self.fetcher.fetch_all(cascade_res.candidates)
        elapsed_fetch = int((time.time() - t0) * 1000)
        total_cand_images = sum(len(fc.images) for fc in fetched_cands)

        step_logs.append(
            PipelineStepLog(
                step_name="candidate_fetcher",
                status="SUCCESS",
                duration_ms=elapsed_fetch,
                details={
                    "fetched_pages": len(fetched_cands),
                    "total_images_downloaded": total_cand_images,
                },
            )
        )

        # ----------------------------------------------------------------------
        # Step 6: Biometric Match Verification & Selection
        # ----------------------------------------------------------------------
        t0 = time.time()
        match_decision = self.matcher.evaluate_candidates(orig_embedding, fetched_cands)
        elapsed_match = int((time.time() - t0) * 1000)

        step_logs.append(
            PipelineStepLog(
                step_name="biometric_matching",
                status="SUCCESS" if match_decision.status == "MATCH_FOUND" else "FAILED",
                duration_ms=elapsed_match,
                details={
                    "status": match_decision.status,
                    "top1_score": match_decision.top1_score,
                    "top2_score": match_decision.top2_score,
                    "margin": match_decision.score_margin,
                    "rejection_reason": match_decision.rejection_reason,
                },
            )
        )

        if match_decision.status != "MATCH_FOUND" or not match_decision.winning_candidate:
            return PipelineExecutionResult(
                status=match_decision.status,
                detection=det_result,
                cascade=cascade_res,
                fetched_candidates=fetched_cands,
                match_decision=match_decision,
                logs=step_logs,
                total_duration_ms=int((time.time() - start_time) * 1000),
                error_message=match_decision.rejection_reason or f"Matching ended with status: {match_decision.status}",
            )

        winning_cand = match_decision.winning_candidate

        # ----------------------------------------------------------------------
        # Step 7: Data Extraction & Two-Tier Split
        # ----------------------------------------------------------------------
        t0 = time.time()
        extracted = PostDataExtractor.extract(winning_cand)

        immutable_data = ImmutableVerifiableData(
            normalized_source_url=extracted.normalized_source_url,
            platform=extracted.platform,
            source_type=extracted.source_type,
            public_post_id=extracted.public_post_id,
            post_text_normalized=extracted.post_text_normalized,
            image_sha256=extracted.image_sha256,
            schema_version=extracted.schema_version,
        )

        content_hash, canonical_bytes = Canonicalizer.create_fingerprint(immutable_data)

        discovery_ts = datetime.datetime.utcnow().isoformat() + "Z"
        audit_metadata = AuditMetadata(
            discovery_timestamp=discovery_ts,
            pipeline_execution_timestamp=discovery_ts,
            similarity_score=float(winning_cand.similarity_score),
            search_provider=cascade_res.winning_provider,
            search_representation_used=cascade_res.winning_representation,
            embedding_model_version=self.embedder.model_version,
            api_response_time_ms=elapsed_search,
            discovery_method=getattr(winning_cand.fetched_candidate.search_result, "discovery_method", "search"),
            confidence_margin=float(match_decision.score_margin),
            image_phash=extracted.image_phash,
        )

        elapsed_canon = int((time.time() - t0) * 1000)
        step_logs.append(
            PipelineStepLog(
                step_name="canonicalization",
                status="SUCCESS",
                duration_ms=elapsed_canon,
                details={
                    "content_hash": content_hash,
                    "canonical_bytes_len": len(canonical_bytes),
                    "platform": extracted.platform,
                },
            )
        )

        # Pre-check for duplicate content in local cache
        existing_cached = self.cache.find_by_content_hash(content_hash)
        if existing_cached:
            logger.info(
                f"[DUPLICATE_CONTENT_DETECTED] Content hash {content_hash[:12]}... already exists under record #{existing_cached[0].record_id}."
            )

        # ----------------------------------------------------------------------
        # Step 8: Optional Human Review Hook (Off by default per PRD Correction 6)
        # ----------------------------------------------------------------------
        if review_callback is not None:
            logger.info("Executing optional human review hook...")
            approved = review_callback(match_decision)
            if not approved:
                logger.warning("Human review rejected the match candidate.")
                return PipelineExecutionResult(
                    status="HUMAN_REJECTED",
                    detection=det_result,
                    cascade=cascade_res,
                    fetched_candidates=fetched_cands,
                    match_decision=match_decision,
                    extracted_data=extracted,
                    immutable_data=immutable_data,
                    content_hash=content_hash,
                    logs=step_logs,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                    error_message="Match was rejected during human review mode.",
                )

        # ----------------------------------------------------------------------
        # Step 9: Blockchain Record Creation
        # ----------------------------------------------------------------------
        receipt = None
        if not skip_blockchain:
            t0 = time.time()
            try:
                receipt = self.writer.submit_record(
                    content_hash=content_hash,
                    metadata_uri=extracted.normalized_source_url,
                )
                elapsed_chain = int((time.time() - t0) * 1000)
                step_logs.append(
                    PipelineStepLog(
                        step_name="blockchain_submission",
                        status="SUCCESS",
                        duration_ms=elapsed_chain,
                        details={
                            "record_id": receipt.record_id,
                            "tx_hash": receipt.tx_hash,
                            "block_number": receipt.block_number,
                            "gas_used": receipt.gas_used,
                            "explorer_url": receipt.explorer_url,
                        },
                    )
                )
            except Exception as e:
                elapsed_chain = int((time.time() - t0) * 1000)
                logger.error(f"Blockchain write failed: {e}")
                step_logs.append(
                    PipelineStepLog(
                        step_name="blockchain_submission",
                        status="FAILED",
                        duration_ms=elapsed_chain,
                        details={"error": str(e)},
                    )
                )
                return PipelineExecutionResult(
                    status="CHAIN_WRITE_ERROR",
                    detection=det_result,
                    cascade=cascade_res,
                    fetched_candidates=fetched_cands,
                    match_decision=match_decision,
                    extracted_data=extracted,
                    immutable_data=immutable_data,
                    content_hash=content_hash,
                    logs=step_logs,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                    error_message=f"Blockchain write error: {e}",
                )

        # ----------------------------------------------------------------------
        # Step 10: Local Cache & Audit Logging
        # ----------------------------------------------------------------------
        cached_rec = None
        if receipt is not None:
            cached_rec = self.cache.save_record(
                record_id=receipt.record_id,
                tx_hash=receipt.tx_hash,
                content_hash=content_hash,
                immutable_data=immutable_data.to_dict(),
                audit_metadata=audit_metadata.to_dict(),
            )

        total_elapsed = int((time.time() - start_time) * 1000)
        logger.info(
            f"==> Pipeline Run Completed Successfully in {total_elapsed}ms! Status: SUCCESS"
        )

        return PipelineExecutionResult(
            status="SUCCESS",
            detection=det_result,
            cascade=cascade_res,
            fetched_candidates=fetched_cands,
            match_decision=match_decision,
            extracted_data=extracted,
            immutable_data=immutable_data,
            audit_metadata=audit_metadata,
            content_hash=content_hash,
            write_receipt=receipt,
            cached_record=cached_rec,
            logs=step_logs,
            total_duration_ms=total_elapsed,
        )
