"""
Unit tests for Canonicalization and Hashing (Regression tests for PRD Correction 3).
"""

import pytest

from pipeline.canon.canonicalize import (
    AuditMetadata,
    Canonicalizer,
    ImmutableVerifiableData,
)


def test_canonicalize_idempotent():
    data = ImmutableVerifiableData(
        normalized_source_url="https://example.com/post/42",
        platform="twitter",
        public_post_id="42",
        post_text_normalized="Verified photo of John Doe",
        image_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        schema_version="1.0",
    )

    hash1, bytes1 = Canonicalizer.create_fingerprint(data)
    hash2, bytes2 = Canonicalizer.create_fingerprint(data)

    assert hash1 == hash2
    assert bytes1 == bytes2
    assert hash1.startswith("0x")
    assert len(hash1) == 66  # 0x + 64 hex chars = 32 bytes


def test_canonicalize_stable_across_rediscovery_runs():
    """
    CRITICAL REGRESSION TEST (PRD Correction 3):
    Re-discovering the same live post at different times yields DIFFERENT audit metadata
    (timestamps, response times, search provider), but MUST yield the EXACT SAME on-chain content hash.
    """
    immutable_data = ImmutableVerifiableData(
        normalized_source_url="https://example.com/user/photo",
        platform="instagram",
        public_post_id="post_999",
        post_text_normalized="Sunny day in Goa",
        image_sha256="abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890abc",
        schema_version="1.0",
    )

    # Run 1: Discovered via Gemini Search at 10:00 AM
    audit1 = AuditMetadata(
        discovery_timestamp="2026-09-06T10:00:00Z",
        pipeline_execution_timestamp="2026-09-06T10:00:02Z",
        similarity_score=0.892,
        search_provider="gemini",
        search_representation_used="full_image",
        embedding_model_version="facenet-inceptionresnetv1-vggface2-512d",
        api_response_time_ms=350,
        image_phash="d4e2a1b9c8f0",
    )
    hash1, _ = Canonicalizer.create_fingerprint(immutable_data)

    # Run 2: Re-discovered a week later via SerpApi at 04:30 PM with different response time & score
    audit2 = AuditMetadata(
        discovery_timestamp="2026-09-13T16:30:00Z",
        pipeline_execution_timestamp="2026-09-13T16:30:03Z",
        similarity_score=0.887,
        search_provider="serpapi",
        search_representation_used="face_crop",
        embedding_model_version="facenet-inceptionresnetv1-vggface2-512d",
        api_response_time_ms=510,
        image_phash="d4e2a1b9c8f0",
    )
    hash2, _ = Canonicalizer.create_fingerprint(immutable_data)

    # Assert hashes are identical despite totally different audit metadata
    assert hash1 == hash2


def test_tamper_sensitivity():
    """Modifying any single immutable field must change the content hash."""
    original = ImmutableVerifiableData(
        normalized_source_url="https://example.com/post/1",
        platform="twitter",
        public_post_id="1",
        post_text_normalized="Authentic post",
        image_sha256="1111111111111111111111111111111111111111111111111111111111111111",
        schema_version="1.0",
    )
    original_hash, _ = Canonicalizer.create_fingerprint(original)

    # Case A: Modified URL
    tampered_url = ImmutableVerifiableData(
        normalized_source_url="https://example.com/post/2",  # Changed 1 -> 2
        platform="twitter",
        public_post_id="1",
        post_text_normalized="Authentic post",
        image_sha256="1111111111111111111111111111111111111111111111111111111111111111",
        schema_version="1.0",
    )
    hash_tampered_url, _ = Canonicalizer.create_fingerprint(tampered_url)
    assert hash_tampered_url != original_hash

    # Case B: Modified image hash
    tampered_img = ImmutableVerifiableData(
        normalized_source_url="https://example.com/post/1",
        platform="twitter",
        public_post_id="1",
        post_text_normalized="Authentic post",
        image_sha256="2222222222222222222222222222222222222222222222222222222222222222",
        schema_version="1.0",
    )
    hash_tampered_img, _ = Canonicalizer.create_fingerprint(tampered_img)
    assert hash_tampered_img != original_hash


def test_missing_mandatory_fields_raise_error():
    """Missing URL or image hash must raise ValueError."""
    invalid_dict = {
        "normalized_source_url": None,
        "image_sha256": "abc",
    }
    with pytest.raises(ValueError):
        Canonicalizer.canonicalize_dict(invalid_dict)
