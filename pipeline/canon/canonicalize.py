"""
Two-Tier Canonicalization and Cryptographic Fingerprint Hashing Module.
Separates Immutable Verifiable Data (part of on-chain hash) from Audit/Run Metadata.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("pipeline.canon")


# Exact required keys in Tier A (Immutable Verifiable Data)
IMMUTABLE_SCHEMA_KEYS = {
    "image_sha256",
    "normalized_source_url",
    "platform",
    "post_text_normalized",
    "public_post_id",
    "schema_version",
    "source_type",
}


@dataclass
class ImmutableVerifiableData:
    """
    Tier A Data: The only fields that determine VERIFIED vs TAMPER DETECTED.
    Must only contain stable properties of the content itself.
    """
    normalized_source_url: str
    platform: str
    public_post_id: Optional[str]
    post_text_normalized: Optional[str]
    image_sha256: str
    source_type: str = "WEB_PAGE"      # SOCIAL_MEDIA | WEB_PAGE | IMAGE_SOURCE
    schema_version: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_sha256": self.image_sha256,
            "normalized_source_url": self.normalized_source_url,
            "platform": self.platform,
            "post_text_normalized": self.post_text_normalized,
            "public_post_id": self.public_post_id,
            "schema_version": self.schema_version,
            "source_type": self.source_type,
        }


@dataclass
class AuditMetadata:
    """
    Tier B Data: Off-chain run-specific telemetry and audit trail.
    Changing these fields NEVER affects the on-chain hash.
    """
    discovery_timestamp: str
    pipeline_execution_timestamp: str
    similarity_score: float
    search_provider: str
    search_representation_used: str
    embedding_model_version: str
    api_response_time_ms: int
    discovery_method: str = "search"
    confidence_margin: float = 0.0
    image_phash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Canonicalizer:
    """
    Canonicalizes immutable records into deterministic JSON bytes
    and produces SHA-256 / keccak256 fingerprints.
    """

    @staticmethod
    def canonicalize_dict(data: Dict[str, Any]) -> bytes:
        """
        Takes an immutable data dictionary and serializes it deterministically:
        - Sorted keys
        - Compact separators (',', ':')
        - UTF-8 encoding
        """
        ver = data.get("schema_version", "2.0")
        immutable_data = {
            "image_sha256": data.get("image_sha256"),
            "normalized_source_url": data.get("normalized_source_url"),
            "platform": data.get("platform"),
            "post_text_normalized": data.get("post_text_normalized"),
            "public_post_id": data.get("public_post_id"),
            "schema_version": ver,
        }
        # Include source_type for schema_version >= 2.0 or when explicitly provided
        if "source_type" in data or ver != "1.0":
            immutable_data["source_type"] = data.get("source_type", "WEB_PAGE")

        # Validate mandatory fields
        if not immutable_data["image_sha256"] or not immutable_data["normalized_source_url"]:
            raise ValueError(
                "Cannot canonicalize: missing mandatory fields ('image_sha256', 'normalized_source_url')."
            )

        canonical_str = json.dumps(
            immutable_data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return canonical_str.encode("utf-8")

    @classmethod
    def canonicalize(cls, data: ImmutableVerifiableData) -> bytes:
        """Serializes an ImmutableVerifiableData dataclass deterministically."""
        return cls.canonicalize_dict(data.to_dict())

    @classmethod
    def compute_sha256_hash(cls, canonical_bytes: bytes) -> str:
        """
        Returns hex string with 0x prefix (e.g. 0xabcdef... bytes32 format).
        """
        raw_hex = hashlib.sha256(canonical_bytes).hexdigest()
        return f"0x{raw_hex}"

    @classmethod
    def create_fingerprint(
        cls,
        immutable_data: ImmutableVerifiableData,
    ) -> Tuple[str, bytes]:
        """
        Returns (content_hash_hex, canonical_bytes).
        """
        c_bytes = cls.canonicalize(immutable_data)
        h_hex = cls.compute_sha256_hash(c_bytes)
        return h_hex, c_bytes
