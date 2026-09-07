"""
Biometric Match Validation and Automatic Candidate Selection.
Compares candidate face embeddings against the original face embedding,
enforces calibrated similarity threshold and margin requirements,
and performs automatic best-match selection.
"""

from dataclasses import dataclass, field
import io
import logging
from typing import List, Optional

import numpy as np
from PIL import Image

from pipeline.face.detector import FaceDetector
from pipeline.face.embedder import FaceEmbedder, compute_cosine_similarity
from pipeline.search.fetch_candidates import CandidateImage, FetchedCandidate

logger = logging.getLogger("pipeline.match.matcher")


@dataclass
class ScoredCandidate:
    """A candidate image evaluated with biometric similarity score."""
    fetched_candidate: FetchedCandidate
    candidate_image: CandidateImage
    similarity_score: float
    face_box: Optional[tuple] = None
    rank: int = 0


@dataclass
class MatchDecision:
    """Final matching outcome from the candidate pool."""
    status: str                         # MATCH_FOUND | NO_MATCH | LOW_CONFIDENCE_MATCH
    winning_candidate: Optional[ScoredCandidate] = None
    all_scored_candidates: List[ScoredCandidate] = field(default_factory=list)
    top1_score: float = 0.0
    top2_score: float = 0.0
    score_margin: float = 0.0
    threshold_applied: float = 0.60
    margin_applied: float = 0.04
    rejection_reason: Optional[str] = None


class BiometricMatcher:
    """
    Evaluates discovered candidate images against the ground truth face embedding.
    Selects the winning match automatically per PRD Section 14.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.60,
        confidence_margin: float = 0.04,
        detector: Optional[FaceDetector] = None,
        embedder: Optional[FaceEmbedder] = None,
    ):
        self.similarity_threshold = similarity_threshold
        self.confidence_margin = confidence_margin
        self.detector = detector or FaceDetector(min_face_size=40, blur_threshold=20.0)
        self.embedder = embedder or FaceEmbedder()

    def evaluate_candidates(
        self,
        original_embedding: np.ndarray,
        fetched_candidates: List[FetchedCandidate],
    ) -> MatchDecision:
        """
        Runs face detection and embedding comparison for all candidate images.
        Applies threshold filtering and margin checks.
        """
        scored_list: List[ScoredCandidate] = []

        logger.info(
            f"Evaluating biometric match for {len(fetched_candidates)} candidate pages..."
        )

        for fc in fetched_candidates:
            for c_img in fc.images:
                try:
                    pil_img = Image.open(io.BytesIO(c_img.image_bytes)).convert("RGB")
                    det_res = self.detector.detect(pil_img)

                    if det_res.success and det_res.crop_image is not None:
                        cand_emb = self.embedder.get_embedding(det_res.crop_image)
                        score = compute_cosine_similarity(original_embedding, cand_emb)

                        logger.info(
                            f"Candidate: {fc.page_url} | Image SHA: {c_img.sha256[:10]}... | "
                            f"Cosine Sim: {score:.4f} (threshold: {self.similarity_threshold})"
                        )

                        scored_list.append(
                            ScoredCandidate(
                                fetched_candidate=fc,
                                candidate_image=c_img,
                                similarity_score=score,
                                face_box=det_res.box,
                            )
                        )
                    else:
                        logger.debug(f"No face detected in candidate image from {fc.page_url}")
                except Exception as e:
                    logger.warning(f"Failed to process candidate image from {fc.page_url}: {e}")

        if not scored_list:
            logger.info("No candidate images contained detectable faces.")
            return MatchDecision(
                status="NO_MATCH",
                threshold_applied=self.similarity_threshold,
                margin_applied=self.confidence_margin,
                rejection_reason="NO_CANDIDATE_FACES_DETECTED",
            )

        # Sort candidates: Primary by biometric similarity, with social media prioritization for comparable scores
        def rank_sort_key(sc: ScoredCandidate):
            score = sc.similarity_score
            st = getattr(sc.fetched_candidate, "source_type", "WEB_PAGE")
            is_social = 1 if st == "SOCIAL_MEDIA" else 0
            # Social media priority boost of 0.025 when biometric score meets threshold
            boosted_score = score + (0.025 if (is_social and score >= self.similarity_threshold) else 0.0)
            return (boosted_score, score)

        scored_list.sort(key=rank_sort_key, reverse=True)
        for idx, sc in enumerate(scored_list):
            sc.rank = idx + 1

        top1 = scored_list[0]
        top1_score = top1.similarity_score
        top2_score = scored_list[1].similarity_score if len(scored_list) > 1 else 0.0
        margin = top1_score - top2_score

        logger.info(
            f"Top-1 Candidate: score={top1_score:.4f} (type={getattr(top1.fetched_candidate, 'source_type', 'WEB_PAGE')}, "
            f"URL: {top1.fetched_candidate.page_url})"
        )
        if len(scored_list) > 1:
            logger.info(f"Top-2 Candidate: score={top2_score:.4f}, margin={margin:.4f}")

        # Check threshold
        if top1_score < self.similarity_threshold:
            logger.info(
                f"Top candidate score ({top1_score:.4f}) is below threshold ({self.similarity_threshold})."
            )
            return MatchDecision(
                status="NO_MATCH",
                all_scored_candidates=scored_list,
                top1_score=top1_score,
                top2_score=top2_score,
                score_margin=margin,
                threshold_applied=self.similarity_threshold,
                margin_applied=self.confidence_margin,
                rejection_reason=f"BELOW_THRESHOLD ({top1_score:.4f} < {self.similarity_threshold})",
            )

        # Check margin if top-2 also exceeds threshold
        if len(scored_list) > 1 and top2_score >= self.similarity_threshold:
            # Margin check applies to ambiguous borderline matches (< 0.85 similarity)
            # If top-1 is an overwhelming biometric match (>= 0.85), multiple public mirrors/copies of the same face are expected
            if margin < self.confidence_margin and top1_score < 0.85:
                logger.warning(
                    f"Ambiguous top candidates! Margin ({margin:.4f}) < required ({self.confidence_margin}). "
                    f"Auto-rejected as LOW_CONFIDENCE_MATCH."
                )
                return MatchDecision(
                    status="LOW_CONFIDENCE_MATCH",
                    winning_candidate=top1,
                    all_scored_candidates=scored_list,
                    top1_score=top1_score,
                    top2_score=top2_score,
                    score_margin=margin,
                    threshold_applied=self.similarity_threshold,
                    margin_applied=self.confidence_margin,
                    rejection_reason=f"INSUFFICIENT_MARGIN ({margin:.4f} < {self.confidence_margin})",
                )

        # Top-1 satisfies both threshold and margin requirements!
        logger.info(
            f"==> AUTOMATIC BEST MATCH CONFIRMED: {top1.fetched_candidate.page_url} "
            f"(Source Type: {getattr(top1.fetched_candidate, 'source_type', 'WEB_PAGE')})"
        )
        return MatchDecision(
            status="MATCH_FOUND",
            winning_candidate=top1,
            all_scored_candidates=scored_list,
            top1_score=top1_score,
            top2_score=top2_score,
            score_margin=margin,
            threshold_applied=self.similarity_threshold,
            margin_applied=self.confidence_margin,
        )
