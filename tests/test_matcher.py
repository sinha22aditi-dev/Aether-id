"""
Unit tests for Biometric Matcher and Decision Logic (PRD Correction 6 & 8).
"""

from unittest.mock import MagicMock
import numpy as np
import pytest

from pipeline.match.matcher import BiometricMatcher, ScoredCandidate
from pipeline.search.base import SearchResult
from pipeline.search.fetch_candidates import CandidateImage, FetchedCandidate


import io
from PIL import Image

def create_mock_candidate(url: str, img_sha: str) -> FetchedCandidate:
    sr = SearchResult(url=url, provider="gemini", representation="full_image")
    # Generate a small valid JPEG byte stream
    img = Image.new("RGB", (50, 50), color=(120, 150, 180))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    valid_bytes = buf.getvalue()

    c_img = CandidateImage(image_url=url + "/img.jpg", image_bytes=valid_bytes, sha256=img_sha)
    return FetchedCandidate(
        search_result=sr,
        page_url=url,
        page_title=f"Page for {url}",
        page_text=f"Sample text for {url}",
        platform="twitter",
        images=[c_img],
    )


def test_matcher_automatic_winner():
    matcher = BiometricMatcher(similarity_threshold=0.60, confidence_margin=0.05)
    # Mock detector & embedder
    matcher.detector = MagicMock()
    det_mock = MagicMock()
    det_mock.success = True
    det_mock.crop_image = MagicMock()
    det_mock.box = (10, 10, 50, 50)
    matcher.detector.detect.return_value = det_mock

    # Mock embedder to return high similarity for candidate 1 and low for candidate 2
    matcher.embedder = MagicMock()
    # Let original embedding be a unit vector
    orig_emb = np.zeros(512, dtype=np.float32)
    orig_emb[0] = 1.0

    emb_cand1 = np.zeros(512, dtype=np.float32)
    emb_cand1[0] = 0.85  # cosine sim ~0.85
    emb_cand1[1] = 0.52678

    emb_cand2 = np.zeros(512, dtype=np.float32)
    emb_cand2[0] = 0.40  # cosine sim ~0.40
    emb_cand2[1] = 0.9165

    matcher.embedder.get_embedding.side_effect = [emb_cand1, emb_cand2]

    cand1 = create_mock_candidate("https://example.com/match", "sha111")
    cand2 = create_mock_candidate("https://example.com/other", "sha222")

    decision = matcher.evaluate_candidates(orig_emb, [cand1, cand2])

    assert decision.status == "MATCH_FOUND"
    assert decision.winning_candidate is not None
    assert decision.winning_candidate.fetched_candidate.page_url == "https://example.com/match"
    assert decision.top1_score > 0.80
    assert decision.score_margin > 0.05


def test_matcher_below_threshold_returns_no_match():
    matcher = BiometricMatcher(similarity_threshold=0.70, confidence_margin=0.05)
    matcher.detector = MagicMock()
    det_mock = MagicMock()
    det_mock.success = True
    det_mock.crop_image = MagicMock()
    matcher.detector.detect.return_value = det_mock

    matcher.embedder = MagicMock()
    orig_emb = np.zeros(512, dtype=np.float32)
    orig_emb[0] = 1.0

    emb_cand = np.zeros(512, dtype=np.float32)
    emb_cand[0] = 0.45  # 0.45 < 0.70
    emb_cand[1] = 0.893
    matcher.embedder.get_embedding.return_value = emb_cand

    cand = create_mock_candidate("https://example.com/low_score", "sha_low")
    decision = matcher.evaluate_candidates(orig_emb, [cand])

    assert decision.status == "NO_MATCH"
    assert decision.winning_candidate is None


def test_matcher_ambiguous_near_tie_rejected():
    matcher = BiometricMatcher(similarity_threshold=0.60, confidence_margin=0.05)
    matcher.detector = MagicMock()
    det_mock = MagicMock()
    det_mock.success = True
    det_mock.crop_image = MagicMock()
    matcher.detector.detect.return_value = det_mock

    matcher.embedder = MagicMock()
    orig_emb = np.zeros(512, dtype=np.float32)
    orig_emb[0] = 1.0

    # Top-1 score: 0.81, Top-2 score: 0.79 -> margin = 0.02 < 0.05
    emb_cand1 = np.zeros(512, dtype=np.float32)
    emb_cand1[0] = 0.81
    emb_cand1[1] = 0.5864

    emb_cand2 = np.zeros(512, dtype=np.float32)
    emb_cand2[0] = 0.79
    emb_cand2[1] = 0.6131

    matcher.embedder.get_embedding.side_effect = [emb_cand1, emb_cand2]

    cand1 = create_mock_candidate("https://example.com/personA", "shaA")
    cand2 = create_mock_candidate("https://example.com/personB", "shaB")

    decision = matcher.evaluate_candidates(orig_emb, [cand1, cand2])

    assert decision.status == "LOW_CONFIDENCE_MATCH"
    assert decision.score_margin < 0.05


def test_matcher_social_media_prioritization():
    """When a Social Media match and a Web Page match have comparable scores, Social Media is prioritized."""
    matcher = BiometricMatcher(similarity_threshold=0.60, confidence_margin=0.05)
    matcher.detector = MagicMock()
    det_mock = MagicMock()
    det_mock.success = True
    det_mock.crop_image = MagicMock()
    matcher.detector.detect.return_value = det_mock

    matcher.embedder = MagicMock()
    orig_emb = np.zeros(512, dtype=np.float32)
    orig_emb[0] = 1.0

    # Web page candidate score: 0.880
    emb_web = np.zeros(512, dtype=np.float32)
    emb_web[0] = 0.880
    emb_web[1] = 0.47497

    # Social media candidate score: 0.875 (very close, within 0.02)
    emb_social = np.zeros(512, dtype=np.float32)
    emb_social[0] = 0.875
    emb_social[1] = 0.48412

    matcher.embedder.get_embedding.side_effect = [emb_web, emb_social]

    cand_web = create_mock_candidate("https://generic-news.com/article/1", "sha_web")
    cand_web.source_type = "WEB_PAGE"

    cand_social = create_mock_candidate("https://twitter.com/user/status/100", "sha_soc")
    cand_social.source_type = "SOCIAL_MEDIA"
    cand_social.search_result.source_type = "SOCIAL_MEDIA"

    decision = matcher.evaluate_candidates(orig_emb, [cand_web, cand_social])

    assert decision.status == "MATCH_FOUND"
    assert decision.winning_candidate.fetched_candidate.source_type == "SOCIAL_MEDIA"
    assert decision.winning_candidate.fetched_candidate.page_url == "https://twitter.com/user/status/100"
